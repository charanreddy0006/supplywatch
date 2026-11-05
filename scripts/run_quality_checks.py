"""Execute and persist source and database quality rules."""
import argparse, json
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from database.connection import make_engine
from database.models import QuarantinedRecord
from quality.engine import run_quality_checks
from quality.metrics import quality_scorecards


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",choices=["all","ports","earthquakes","integrity"],default="all")
    parser.add_argument("--ingestion-run-id")
    parser.add_argument("--source-name",help="Required with --ingestion-run-id to link the execution to a source run")
    parser.add_argument("--json",action="store_true",help="Print the full structured execution result")
    args=parser.parse_args()
    if bool(args.ingestion_run_id)!=bool(args.source_name):
        parser.error("--ingestion-run-id and --source-name must be supplied together")
    engine=make_engine()
    try:
        with Session(engine) as session, session.begin():
            run=run_quality_checks(session,args.dataset,args.ingestion_run_id,args.source_name)
            scorecards=quality_scorecards(session,run.execution_id)
            quarantines={status:int(count) for status,count in session.execute(select(QuarantinedRecord.status,func.count()).group_by(QuarantinedRecord.status)).all()}
            output={**run.to_dict(),"scorecards":scorecards,"quarantine_counts":quarantines}
        if args.json:
            print(json.dumps(output,indent=2,default=str))
        else:
            failed=[row for row in run.rules if not row["passed"]]
            print(f"Execution {run.execution_id} | dataset={args.dataset} | status={run.status} | rules={len(run.rules)} passed={len(run.rules)-len(failed)} failed={len(failed)}")
            for dataset in ("ports","earthquakes","platform"):
                print(f"\n{dataset.upper()} scorecard")
                for dimension,metric in scorecards[dataset].items():
                    if metric["rules"] or metric["records_excluded"]:
                        pct="n/a" if metric["percentage"] is None else f"{metric['percentage']:.2f}%"
                        print(f"  {dimension}: {pct} | evaluated={metric['records_evaluated']} passed={metric['records_passed']} failed={metric['records_failed']} excluded={metric['records_excluded']}")
            print(f"\nQuarantine: {quarantines}")
            if failed:
                print("Failed rules:")
                for row in failed:
                    print(f"  {row['severity']} {row['rule_id']}: {row['records_failed']} record failures")
        if any(not row["passed"] for row in run.rules):
            raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Quality check failed: {type(exc).__name__}: {exc}")
        raise SystemExit(2)
    finally:
        engine.dispose()


if __name__=="__main__": main()
