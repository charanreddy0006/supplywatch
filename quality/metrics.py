"""Transparent dimension scorecards derived from persisted rule results."""
from sqlalchemy import select
from database.models import QualityExecution, QualityRuleResult

DIMENSIONS=("completeness","validity","uniqueness","consistency","timeliness","referential_integrity")


def quality_scorecards(session, execution_id: str):
    execution=session.get(QualityExecution,execution_id)
    if execution is None:
        raise LookupError(f"Quality execution {execution_id} was not found")
    rows=session.execute(select(QualityRuleResult).where(QualityRuleResult.execution_id==execution_id)).scalars().all()
    by_dataset={"ports":{},"earthquakes":{},"platform":{}}
    for row in rows:
        target=row.dataset if row.dataset in {"ports","earthquakes"} else "platform"
        bucket=by_dataset[target].setdefault(row.dimension,{"records_evaluated":0,"records_passed":0,"records_failed":0,"records_excluded":0,"rules":[]})
        bucket["records_evaluated"]+=row.records_evaluated
        bucket["records_passed"]+=row.records_passed
        bucket["records_failed"]+=row.records_failed
        bucket["records_excluded"]+=row.records_excluded
        bucket["rules"].append(row.rule_id)
    result={}
    for dataset,dimensions in by_dataset.items():
        result[dataset]={}
        for dimension in DIMENSIONS:
            metric=dimensions.get(dimension,{"records_evaluated":0,"records_passed":0,"records_failed":0,"records_excluded":0,"rules":[]})
            den=metric["records_passed"]+metric["records_failed"]
            metric["percentage"]=(round(100*metric["records_passed"]/den,2) if den else None)
            metric["percentage_basis"]="records_passed / (records_passed + records_failed); excluded records do not enter denominator"
            metric["rules"].sort()
            result[dataset][dimension]=metric
    return {"execution_id":execution_id,"ports":result["ports"],"earthquakes":result["earthquakes"],"platform":result["platform"]}


def compare_quality_executions(session, first_id: str, second_id: str):
    first=quality_scorecards(session,first_id); second=quality_scorecards(session,second_id)
    comparison={"first_execution_id":first_id,"second_execution_id":second_id,"dimensions":{}}
    for dataset in ("ports","earthquakes","platform"):
        comparison["dimensions"][dataset]={}
        for dimension in DIMENSIONS:
            left=first[dataset][dimension]["percentage"]
            right=second[dataset][dimension]["percentage"]
            comparison["dimensions"][dataset][dimension]={"first_percent":left,"second_percent":right,"change_percentage_points":round(right-left,2) if left is not None and right is not None else None}
    return comparison
