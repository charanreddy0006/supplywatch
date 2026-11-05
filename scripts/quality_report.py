"""Print persisted quality scorecards or compare two executions."""
import argparse, json
from sqlalchemy.orm import Session
from database.connection import make_engine
from quality.metrics import quality_scorecards, compare_quality_executions


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--execution-id")
    group.add_argument("--compare",nargs=2,metavar=("FIRST","SECOND"))
    parser.add_argument("--json",action="store_true",help="Print full JSON output")
    args=parser.parse_args(); engine=make_engine()
    try:
        with Session(engine) as session:
            output=quality_scorecards(session,args.execution_id) if args.execution_id else compare_quality_executions(session,*args.compare)
            if args.json:
                print(json.dumps(output,indent=2,default=str))
            elif "ports" in output:
                print(f"Quality execution {output['execution_id']}")
                for dataset in ("ports","earthquakes","platform"):
                    print(f"\n{dataset.upper()}")
                    for dimension,metric in output[dataset].items():
                        if metric["rules"] or metric["records_excluded"]:
                            percent="n/a" if metric["percentage"] is None else f"{metric['percentage']:.2f}%"
                            print(f"  {dimension}: {percent} | pass={metric['records_passed']} fail={metric['records_failed']} excluded={metric['records_excluded']}")
            else:
                print(f"Quality trend: {output['first_execution_id']} -> {output['second_execution_id']}")
                for dataset,dimensions in output["dimensions"].items():
                    print(f"\n{dataset.upper()}")
                    for dimension,values in dimensions.items():
                        if values["first_percent"] is not None or values["second_percent"] is not None:
                            print(f"  {dimension}: {values['first_percent']}% -> {values['second_percent']}% ({values['change_percentage_points']} pp)")
    except Exception as exc:
        print(f"Quality report failed: {type(exc).__name__}: {exc}")
        raise SystemExit(2)
    finally: engine.dispose()


if __name__=="__main__": main()
