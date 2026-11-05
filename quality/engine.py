"""Persisted rule execution engine for source and database quality checks."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from database.models import QualityExecution, QualityIssue, QualityRuleResult
from quality.rules import rules_for, evaluate_rule, quarantine_rule_failure


def _safe(value):
    if isinstance(value, dict): return {str(k): _safe(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [_safe(v) for v in value]
    if isinstance(value, (datetime,)): return value.isoformat()
    if isinstance(value, Decimal): return str(value)
    return value


def _issue_observed(issue):
    if "observed_value" in issue:
        return issue["observed_value"]
    return {k:v for k,v in issue.items() if not k.startswith("_") and k not in {"entity_identifier","error_description"}}


@dataclass
class QualityRun:
    execution_id: str
    status: str
    rules: list[dict]
    metrics: dict
    critical_or_high_failures: int

    def to_dict(self):
        return {"execution_id":self.execution_id,"status":self.status,"rules":self.rules,"metrics":self.metrics,"critical_or_high_failures":self.critical_or_high_failures}


def run_quality_checks(session: Session, dataset="all", ingestion_run_id=None, ingestion_source_name=None) -> QualityRun:
    started=datetime.now(timezone.utc)
    execution_id=str(uuid4())
    execution=QualityExecution(execution_id=execution_id,dataset=dataset,ingestion_run_id=ingestion_run_id,
        ingestion_source_name=ingestion_source_name,started_at=started,status="running",execution_metadata={"engine":"supplywatch-quality-v1"})
    session.add(execution); session.flush()
    public_results=[]
    dimension_counts={}
    critical_or_high=0
    for rule in rules_for(dataset):
        evaluation=evaluate_rule(session,rule)
        failure_count=sum(int(issue.get("_failed_records",1)) for issue in evaluation.issues)
        evaluated=max(0,int(evaluation.total))
        passed=max(0,evaluated-failure_count)
        result=QualityRuleResult(execution_id=execution_id,rule_id=rule.rule_id,rule_name=rule.name,dataset=rule.dataset,
            severity=rule.severity,dimension=rule.dimension,passed=failure_count==0,records_evaluated=evaluated,
            records_passed=passed,records_failed=failure_count,records_excluded=int(evaluation.excluded),
            expected_condition=rule.expected,observed_value={"issue_count":len(evaluation.issues),"diagnostics":_safe(evaluation.diagnostics or {})},
            error_description=rule.description if failure_count else None,executed_at=datetime.now(timezone.utc),diagnostics={"validation_layer":rule.validation_layer,**_safe(evaluation.diagnostics or {})})
        session.add(result); session.flush()
        for issue in evaluation.issues:
            record=QualityIssue(execution_id=execution_id,rule_result_id=result.id,rule_id=rule.rule_id,dataset=rule.dataset,
                entity_identifier=issue.get("entity_identifier"),severity=rule.severity,expected_condition=rule.expected,
                observed_value=_safe(_issue_observed(issue)),error_description=issue.get("error_description") or rule.description,
                detected_at=datetime.now(timezone.utc),status="OPEN")
            session.add(record)
            quarantine_rule_failure(session,rule,issue)
        bucket=dimension_counts.setdefault(rule.dimension,{"records_evaluated":0,"records_passed":0,"records_failed":0,"records_excluded":0,"rules":[]})
        bucket["records_evaluated"]+=evaluated
        bucket["records_passed"]+=passed
        bucket["records_failed"]+=failure_count
        bucket["records_excluded"]+=int(evaluation.excluded)
        bucket["rules"].append(rule.rule_id)
        if failure_count and rule.severity in {"CRITICAL","HIGH"}:
            critical_or_high+=failure_count
        public_results.append({"rule_id":rule.rule_id,"rule_name":rule.name,"dataset":rule.dataset,"severity":rule.severity,
            "dimension":rule.dimension,"validation_layer":rule.validation_layer,"passed":failure_count==0,"records_evaluated":evaluated,"records_passed":passed,
            "records_failed":failure_count,"records_excluded":int(evaluation.excluded),"expected":rule.expected,
            "observed":{"issue_count":len(evaluation.issues),**_safe(evaluation.diagnostics or {})},
            "errors":[{"entity_identifier":i.get("entity_identifier"),"observed_value":_safe(_issue_observed(i)),"error":i.get("error_description") or rule.description} for i in evaluation.issues]})
    execution.status="completed"
    execution.completed_at=datetime.now(timezone.utc)
    execution.execution_metadata={"engine":"supplywatch-quality-v1","rule_count":len(public_results),"failed_rule_count":sum(not r["passed"] for r in public_results)}
    session.flush()
    return QualityRun(execution_id,"completed",public_results,dimension_counts,critical_or_high)
