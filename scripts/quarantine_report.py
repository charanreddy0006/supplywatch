"""Inspect quarantined source records and run guarded revalidation."""
import argparse, json
from sqlalchemy import select
from sqlalchemy.orm import Session
from database.connection import make_engine
from database.models import QuarantinedRecord
from quality.quarantine import revalidate_quarantine, transition_quarantine


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status",choices=["QUARANTINED","UNDER_REVIEW","READY_FOR_REPROCESSING","RESOLVED"])
    parser.add_argument("--revalidate",type=int,metavar="ID",help="Revalidate one record; only valid payloads become ready")
    parser.add_argument("--resolve",type=int,metavar="ID",help="Mark a READY_FOR_REPROCESSING record resolved after external reprocessing")
    parser.add_argument("--notes",default=None)
    args=parser.parse_args()
    if args.revalidate and args.resolve: parser.error("Choose either --revalidate or --resolve")
    engine=make_engine()
    try:
        with Session(engine) as session, session.begin():
            if args.revalidate:
                record,ready=revalidate_quarantine(session,args.revalidate)
                print(json.dumps({"id":record.id,"status":record.status,"ready":ready,"error_codes":record.error_codes,"notes":record.resolution_notes},indent=2))
            elif args.resolve:
                record=session.get(QuarantinedRecord,args.resolve)
                if record is None: raise LookupError(f"Quarantined record {args.resolve} not found")
                transition_quarantine(record,"RESOLVED",notes=args.notes)
                print(json.dumps({"id":record.id,"status":record.status,"notes":record.resolution_notes},indent=2))
            else:
                stmt=select(QuarantinedRecord).order_by(QuarantinedRecord.quarantined_at.desc())
                if args.status: stmt=stmt.where(QuarantinedRecord.status==args.status)
                rows=session.execute(stmt).scalars().all()
                print(json.dumps([{c.key:getattr(row,c.key) for c in row.__mapper__.column_attrs} for row in rows],indent=2,default=str))
    except Exception as exc:
        print(f"Quarantine operation failed: {type(exc).__name__}: {exc}")
        raise SystemExit(2)
    finally: engine.dispose()


if __name__=="__main__": main()
