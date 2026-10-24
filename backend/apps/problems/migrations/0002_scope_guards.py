from django.db import migrations

FORWARD = """
CREATE FUNCTION problem_asset_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE problem_child uuid; asset_child uuid;
BEGIN
  SELECT child_id INTO problem_child FROM problems_problem WHERE id=NEW.problem_id;
  SELECT child_id INTO asset_child FROM problems_asset WHERE id=NEW.asset_id;
  IF problem_child IS DISTINCT FROM asset_child THEN
    RAISE EXCEPTION 'Problem asset scope mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER problem_asset_scope BEFORE INSERT OR UPDATE ON problems_problemasset
FOR EACH ROW EXECUTE FUNCTION problem_asset_scope_guard();

CREATE FUNCTION asset_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE object_child uuid; object_family uuid; child_family uuid; parent_child uuid;
BEGIN
  IF TG_OP='UPDATE' AND OLD.child_id IS DISTINCT FROM NEW.child_id THEN
    RAISE EXCEPTION 'Asset scope is immutable' USING ERRCODE='23514';
  END IF;
  SELECT child_id,family_id INTO object_child,object_family
    FROM problems_storedobject WHERE id=NEW.object_id;
  SELECT family_id INTO child_family FROM accounts_childprofile WHERE id=NEW.child_id;
  IF object_child IS DISTINCT FROM NEW.child_id OR object_family IS DISTINCT FROM child_family THEN
    RAISE EXCEPTION 'Stored object scope mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.parent_id IS NOT NULL THEN
    SELECT child_id INTO parent_child FROM problems_asset WHERE id=NEW.parent_id;
    IF parent_child IS DISTINCT FROM NEW.child_id THEN
      RAISE EXCEPTION 'Derived image scope mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER asset_scope BEFORE INSERT OR UPDATE ON problems_asset
FOR EACH ROW EXECUTE FUNCTION asset_scope_guard();

CREATE FUNCTION problem_text_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE text_problem uuid; is_confirmed boolean;
BEGIN
  IF TG_OP='UPDATE' AND OLD.child_id IS DISTINCT FROM NEW.child_id THEN
    RAISE EXCEPTION 'Problem scope is immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.current_text_id IS NOT NULL THEN
    SELECT problem_id,confirmed INTO text_problem,is_confirmed
      FROM problems_problemtextversion WHERE id=NEW.current_text_id;
    IF text_problem IS DISTINCT FROM NEW.id OR NOT is_confirmed THEN
      RAISE EXCEPTION 'Current text must be confirmed and owned' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER problem_text_scope BEFORE INSERT OR UPDATE ON problems_problem
FOR EACH ROW EXECUTE FUNCTION problem_text_scope_guard();

CREATE FUNCTION ocr_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE scope_child uuid; scope_family uuid;
BEGIN
  IF TG_OP='UPDATE' THEN
    IF OLD.billing_mode IS DISTINCT FROM NEW.billing_mode
       OR OLD.credential_id IS DISTINCT FROM NEW.credential_id
       OR OLD.credential_version IS DISTINCT FROM NEW.credential_version
       OR OLD.snapshot IS DISTINCT FROM NEW.snapshot
       OR OLD.price_snapshot IS DISTINCT FROM NEW.price_snapshot
       OR OLD.family_id IS DISTINCT FROM NEW.family_id
       OR OLD.child_id IS DISTINCT FROM NEW.child_id OR OLD.actor_id IS DISTINCT FROM NEW.actor_id
       OR OLD.model_id IS DISTINCT FROM NEW.model_id
       OR OLD.price_id IS DISTINCT FROM NEW.price_id THEN
      RAISE EXCEPTION 'OCR binding is immutable' USING ERRCODE='23514';
    END IF;
    IF (NEW.problem_id IS NULL OR NEW.asset_id IS NULL) THEN RETURN NEW; END IF;
    IF OLD.problem_id IS DISTINCT FROM NEW.problem_id
       OR OLD.asset_id IS DISTINCT FROM NEW.asset_id THEN
      RAISE EXCEPTION 'OCR input is immutable' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  SELECT p.child_id,c.family_id INTO scope_child,scope_family FROM problems_problem p
  JOIN accounts_childprofile c ON c.id=p.child_id WHERE p.id=NEW.problem_id;
  IF scope_child IS DISTINCT FROM NEW.child_id OR scope_family IS DISTINCT FROM NEW.family_id
     OR NOT EXISTS(SELECT 1 FROM problems_problemasset
       WHERE problem_id=NEW.problem_id AND asset_id=NEW.asset_id) THEN
    RAISE EXCEPTION 'OCR input scope mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER ocr_scope BEFORE INSERT OR UPDATE ON ocr_ocrjob
FOR EACH ROW EXECUTE FUNCTION ocr_scope_guard();
"""

REVERSE = """
DROP TRIGGER ocr_scope ON ocr_ocrjob;
DROP FUNCTION ocr_scope_guard();
DROP TRIGGER problem_text_scope ON problems_problem;
DROP FUNCTION problem_text_scope_guard();
DROP TRIGGER asset_scope ON problems_asset;
DROP FUNCTION asset_scope_guard();
DROP TRIGGER problem_asset_scope ON problems_problemasset;
DROP FUNCTION problem_asset_scope_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("problems", "0001_initial"),
        ("ocr", "0002_initial"),
        ("metering", "0002_initial"),
    ]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
