from django.db import migrations

SQL = """
CREATE FUNCTION bank_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF ROW(NEW.name,NEW.source_type,NEW.source_reference,NEW.license_name,NEW.rights_evidence,
         NEW.attribution,NEW.usage_conditions,NEW.allow_public,NEW.valid_from,NEW.valid_until)
     IS DISTINCT FROM
     ROW(OLD.name,OLD.source_type,OLD.source_reference,OLD.license_name,OLD.rights_evidence,
         OLD.attribution,OLD.usage_conditions,OLD.allow_public,OLD.valid_from,OLD.valid_until) THEN
    NEW.revision := OLD.revision+1; NEW.review_status := 'pending';
    NEW.reviewed_digest := ''; NEW.reviewed_at := NULL; NEW.reviewed_by_id := NULL;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bank_source_change BEFORE UPDATE ON question_bank_questionsource
FOR EACH ROW EXECUTE FUNCTION bank_source_guard();

CREATE FUNCTION bank_item_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF ROW(NEW.source_id,NEW.text,NEW.answer,NEW.explanation,NEW.answer_source,
         NEW.explanation_source,NEW.grade,NEW.question_type,NEW.solution_structure,
         NEW.difficulty,NEW.knowledge_points,NEW.math_spec)
     IS DISTINCT FROM
     ROW(OLD.source_id,OLD.text,OLD.answer,OLD.explanation,OLD.answer_source,
         OLD.explanation_source,OLD.grade,OLD.question_type,OLD.solution_structure,
         OLD.difficulty,OLD.knowledge_points,OLD.math_spec) THEN
    NEW.revision := OLD.revision+1; NEW.review_status := 'pending'; NEW.reviewed_hash := '';
    NEW.reviewed_source_revision := NULL; NEW.reviewed_by_id := NULL; NEW.reviewed_at := NULL;
    NEW.verification_status := 'imported_unverified'; NEW.verification_method := '';
    NEW.verified_by_id := NULL; NEW.verified_at := NULL;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bank_item_change BEFORE UPDATE ON question_bank_questionbankitem
FOR EACH ROW EXECUTE FUNCTION bank_item_guard();

CREATE FUNCTION bank_check_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF ROW(NEW.id,NEW.created_at,NEW.item_id,NEW.revision,NEW.content_hash,NEW.result)
     IS DISTINCT FROM
     ROW(OLD.id,OLD.created_at,OLD.item_id,OLD.revision,OLD.content_hash,OLD.result)
     OR (NEW.actor_id IS DISTINCT FROM OLD.actor_id AND NEW.actor_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Verification history is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bank_check_change BEFORE UPDATE ON question_bank_verificationrecord
FOR EACH ROW EXECUTE FUNCTION bank_check_guard();

CREATE FUNCTION bank_variant_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='UPDATE' THEN
    IF (to_jsonb(NEW)-'created_by_id') IS DISTINCT FROM (to_jsonb(OLD)-'created_by_id')
       OR (NEW.created_by_id IS DISTINCT FROM OLD.created_by_id AND NEW.created_by_id IS NOT NULL)
    THEN RAISE EXCEPTION 'Variant drafts are immutable' USING ERRCODE='23514'; END IF;
  ELSE
    IF NEW.verification_status <> 'generated_unverified'
       OR NEW.generator <> 'deterministic-variants-v1'
       OR NOT EXISTS (SELECT 1 FROM problems_problemtextversion t
         WHERE t.id=NEW.text_version_id AND t.problem_id=NEW.problem_id AND t.confirmed)
    THEN RAISE EXCEPTION 'Invalid variant draft binding' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bank_variant_change BEFORE INSERT OR UPDATE ON question_bank_variantdraft
FOR EACH ROW EXECUTE FUNCTION bank_variant_guard();
"""

REVERSE = """
DROP TRIGGER bank_variant_change ON question_bank_variantdraft;
DROP FUNCTION bank_variant_guard();
DROP TRIGGER bank_check_change ON question_bank_verificationrecord;
DROP FUNCTION bank_check_guard();
DROP TRIGGER bank_item_change ON question_bank_questionbankitem;
DROP FUNCTION bank_item_guard();
DROP TRIGGER bank_source_change ON question_bank_questionsource;
DROP FUNCTION bank_source_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("question_bank", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
