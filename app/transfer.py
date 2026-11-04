"""Transfers: put patient P into bed `to`.

  * to is FREE      -> from becomes FREE, to becomes OCCUPIED by P
  * to is OCCUPIED  -> the two patients swap beds (step-up / step-down)
  * P already in to -> nothing to do (the other half of a swap already ran)

One transaction:
  START TRANSACTION
    SELECT ... FROM bed WHERE bed_id = <first>  FOR UPDATE
    SELECT ... FROM bed WHERE bed_id = <second> FOR UPDATE
    INSERT INTO transfer (..., 'PENDING')
    UPDATE bed ... (move or swap)
    UPDATE transfer SET status = 'DONE'
  COMMIT

Lock order is the whole deadlock story:
  * ordered (default): lock the lower bed_id first. Two crossing transfers then
    queue on the same first row and can never wait on each other in a circle.
  * request order: lock `from` first, then `to`. Transfer A (101 -> 105) and
    transfer B (105 -> 101) each hold one bed and wait for the other: a cycle.
    InnoDB detects it, rolls one back with error 1213, the other completes.

Why the transfer row is inserted AFTER the beds are locked: transfer has foreign
keys to bed, and an INSERT checks a foreign key by taking a shared (S) lock on the
parent bed row. Inserted first, as its own statement, it would take S locks on both
beds in no particular order and could deadlock against a transfer already holding
an X lock, even with ordered locking. After our own X locks, those checks are free.
"""
import pymysql

from . import db, meta
from . import redis_client as rc


class TransferRefused(Exception):
    pass


def transfer(patient_id, from_bed, to_bed, ordered=True, pause=0.0, label=None,
             user_id=None, crash_hook=None):
    label = label or f"Transfer patient {patient_id}: bed {from_bed} -> {to_bed}"
    result = {"label": label, "patient_id": patient_id, "from_bed": from_bed, "to_bed": to_bed,
              "ordered": ordered, "outcome": None, "transfer_id": None}
    touched = set()
    lock_order = sorted([from_bed, to_bed]) if ordered else [from_bed, to_bed]
    with db.Session(label, user_id) as s:
        result["tx"], result["conn"] = s.tx, s.conn_id
        try:
            s.begin()
            beds = {}
            for i, bed_id in enumerate(lock_order):
                beds[bed_id] = s.one(
                    "SELECT bed_id, status, patient_id, hospital_id, bed_type_id FROM bed WHERE bed_id = %s FOR UPDATE",
                    (bed_id,))
                if beds[bed_id] is None:
                    raise TransferRefused(f"Bed {bed_id} does not exist")
                if i == 0 and pause:
                    s.run(f"SELECT SLEEP({float(pause):g})")
            src, dst = beds[from_bed], beds[to_bed]
            touched = {(src["hospital_id"], src["bed_type_id"]), (dst["hospital_id"], dst["bed_type_id"])}

            s.run("INSERT INTO transfer (patient_id, from_bed_id, to_bed_id, status) VALUES (%s, %s, %s, 'PENDING')",
                  (patient_id, from_bed, to_bed))
            result["transfer_id"] = transfer_id = s.lastrowid

            if dst["patient_id"] == patient_id:
                note = "Patient already in target bed (other half of the swap ran first)"
            elif src["patient_id"] != patient_id:
                raise TransferRefused(f"Patient {patient_id} is not in bed {from_bed}")
            elif dst["status"] == "OCCUPIED":
                other = dst["patient_id"]
                s.run("UPDATE bed SET patient_id = %s WHERE bed_id = %s", (other, from_bed))
                s.run("UPDATE bed SET patient_id = %s WHERE bed_id = %s", (patient_id, to_bed))
                note = f"Swapped with patient {other}"
            elif dst["status"] == "FREE":
                s.run("UPDATE bed SET status = 'FREE', patient_id = NULL WHERE bed_id = %s", (from_bed,))
                if crash_hook:
                    crash_hook(s)
                s.run("UPDATE bed SET status = 'OCCUPIED', patient_id = %s WHERE bed_id = %s", (patient_id, to_bed))
                note = "Moved to a free bed"
            else:
                raise TransferRefused(f"Target bed {to_bed} is {dst['status']}")

            s.run("UPDATE transfer SET status = 'DONE', note = %s WHERE transfer_id = %s", (note, transfer_id))
            s.commit()
            result.update(outcome="DONE", note=note)
        except TransferRefused as exc:
            s.rollback()
            _record_failure(s, patient_id, from_bed, to_bed, str(exc))
            result.update(outcome="REFUSED", error=str(exc))
        except pymysql.MySQLError as exc:
            code = db.err_code(exc)
            result.update(code=code, error=db.err_text(exc), meaning=db.ERROR_MEANING.get(code))
            if code in db.CONNECTION_ERRORS:
                s.in_tx = False
                result["outcome"] = "CONNECTION_LOST"
            else:
                try:
                    s.rollback()
                except Exception:
                    pass
                reason = "Deadlock victim (error 1213), rolled back by InnoDB" if code == 1213 else f"MySQL error {code}"
                result["transfer_id"] = _record_failure(s, patient_id, from_bed, to_bed, reason)
                result["outcome"] = "ROLLED_BACK"

        if result["outcome"] == "DONE":
            for h, t in touched:
                rc.refresh_counter(h, t, session=s)
        result["trace"] = s.trace

    if result["outcome"] != "CONNECTION_LOST":
        rc.publish({"kind": "transfer", "outcome": result["outcome"], "transfer_id": result.get("transfer_id"),
                    "from_bed": from_bed, "to_bed": to_bed})
    return result


def _record_failure(s, patient_id, from_bed, to_bed, reason):
    """The failed attempt is kept as history: a fresh row, PENDING then ROLLED_BACK (the trigger audits it)."""
    try:
        s.run("INSERT INTO transfer (patient_id, from_bed_id, to_bed_id, status) VALUES (%s, %s, %s, 'PENDING')",
              (patient_id, from_bed, to_bed))
        tid = s.lastrowid
        s.run("UPDATE transfer SET status = 'ROLLED_BACK', note = %s WHERE transfer_id = %s", (reason[:120], tid))
        return tid
    except pymysql.MySQLError:
        return None


def hospital_of(bed_id):
    return meta.hospital_name(bed_id // 100)
