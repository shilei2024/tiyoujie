from django.db import migrations

SQL = """
CREATE FUNCTION practice_item_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.worksheet_id IS DISTINCT FROM OLD.worksheet_id
     OR NEW.origin IS DISTINCT FROM OLD.origin
     OR NEW.problem_id IS DISTINCT FROM OLD.problem_id
     OR NEW.bank_item_id IS DISTINCT FROM OLD.bank_item_id
     OR NEW.bank_revision IS DISTINCT FROM OLD.bank_revision
     OR NEW.text IS DISTINCT FROM OLD.text
     OR NEW.answer IS DISTINCT FROM OLD.answer
     OR NEW.explanation IS DISTINCT FROM OLD.explanation
     OR NEW.knowledge_points IS DISTINCT FROM OLD.knowledge_points
     OR NEW.math_spec IS DISTINCT FROM OLD.math_spec
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
  THEN
    RAISE EXCEPTION 'Worksheet item snapshots are immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER practice_item_change BEFORE UPDATE ON practice_worksheetitem
FOR EACH ROW EXECUTE FUNCTION practice_item_guard();

CREATE FUNCTION practice_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'Attempts are append-only' USING ERRCODE='23514';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM practice_worksheetitem i JOIN practice_worksheet w ON w.id=i.worksheet_id
    WHERE i.id=NEW.item_id AND w.deleted_at IS NULL
  ) THEN
    RAISE EXCEPTION 'Attempt requires a live worksheet item' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER practice_attempt_change BEFORE INSERT OR UPDATE ON practice_attempt
FOR EACH ROW EXECUTE FUNCTION practice_attempt_guard();

CREATE FUNCTION practice_review_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'Review events are append-only' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER practice_review_event_change BEFORE UPDATE ON practice_reviewevent
FOR EACH ROW EXECUTE FUNCTION practice_review_event_guard();

CREATE FUNCTION practice_export_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.nonce IS DISTINCT FROM OLD.nonce
     OR NEW.kind IS DISTINCT FROM OLD.kind
     OR NEW.child_id IS DISTINCT FROM OLD.child_id
     OR NEW.worksheet_id IS DISTINCT FROM OLD.worksheet_id
     OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
     OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
  THEN
    RAISE EXCEPTION 'Export ticket identity is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER practice_export_change BEFORE UPDATE ON practice_exportticket
FOR EACH ROW EXECUTE FUNCTION practice_export_guard();
"""

REVERSE = """
DROP TRIGGER practice_export_change ON practice_exportticket;
DROP FUNCTION practice_export_guard();
DROP TRIGGER practice_review_event_change ON practice_reviewevent;
DROP FUNCTION practice_review_event_guard();
DROP TRIGGER practice_attempt_change ON practice_attempt;
DROP FUNCTION practice_attempt_guard();
DROP TRIGGER practice_item_change ON practice_worksheetitem;
DROP FUNCTION practice_item_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("practice", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
