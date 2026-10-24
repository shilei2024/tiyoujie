import importlib

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION ocr_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
       OR OLD.model_id IS DISTINCT FROM NEW.model_id OR OLD.price_id IS DISTINCT FROM NEW.price_id
       OR OLD.task_type IS DISTINCT FROM NEW.task_type
       OR OLD.input_sha256 IS DISTINCT FROM NEW.input_sha256
       OR OLD.input_revision IS DISTINCT FROM NEW.input_revision
       OR OLD.profile_consent_id IS DISTINCT FROM NEW.profile_consent_id
       OR OLD.provider_consent_id IS DISTINCT FROM NEW.provider_consent_id
       OR (NEW.problem_id IS NOT NULL AND OLD.problem_id IS DISTINCT FROM NEW.problem_id)
       OR (NEW.asset_id IS NOT NULL AND OLD.asset_id IS DISTINCT FROM NEW.asset_id)
       OR (NEW.text_version_id IS NOT NULL
           AND OLD.text_version_id IS DISTINCT FROM NEW.text_version_id) THEN
      RAISE EXCEPTION 'AI binding is immutable' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  SELECT p.child_id,c.family_id INTO scope_child,scope_family FROM problems_problem p
  JOIN accounts_childprofile c ON c.id=p.child_id WHERE p.id=NEW.problem_id;
  IF scope_child IS DISTINCT FROM NEW.child_id OR scope_family IS DISTINCT FROM NEW.family_id THEN
    RAISE EXCEPTION 'AI input scope mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.task_type='ocr' THEN
    IF NEW.text_version_id IS NOT NULL OR NOT EXISTS(SELECT 1 FROM problems_problemasset
       WHERE problem_id=NEW.problem_id AND asset_id=NEW.asset_id) THEN
      RAISE EXCEPTION 'OCR image scope mismatch' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.task_type='analysis' THEN
    IF NEW.asset_id IS NOT NULL OR NOT EXISTS(SELECT 1 FROM problems_problemtextversion
       WHERE id=NEW.text_version_id AND problem_id=NEW.problem_id AND confirmed) THEN
      RAISE EXCEPTION 'Analysis text scope mismatch' USING ERRCODE='23514';
    END IF;
  ELSE
    RAISE EXCEPTION 'Unknown AI task type' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION analysis_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM ocr_ocrjob WHERE id=NEW.job_id
      AND task_type='analysis' AND problem_id=NEW.problem_id) THEN
    RAISE EXCEPTION 'Analysis job scope mismatch' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' AND (OLD.problem_id IS DISTINCT FROM NEW.problem_id
      OR OLD.job_id IS DISTINCT FROM NEW.job_id) THEN
    RAISE EXCEPTION 'Analysis scope is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER analysis_input_scope BEFORE INSERT OR UPDATE ON ai_tutor_analysisinput
FOR EACH ROW EXECUTE FUNCTION analysis_scope_guard();
CREATE TRIGGER analysis_result_scope BEFORE INSERT OR UPDATE ON ai_tutor_analysis
FOR EACH ROW EXECUTE FUNCTION analysis_scope_guard();

CREATE FUNCTION analysis_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.payload IS DISTINCT FROM NEW.payload THEN
    RAISE EXCEPTION 'Analysis history is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER analysis_history BEFORE UPDATE ON ai_tutor_analysis
FOR EACH ROW EXECUTE FUNCTION analysis_history_guard();

CREATE FUNCTION analysis_input_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.student_answer IS DISTINCT FROM NEW.student_answer OR OLD.grade IS DISTINCT FROM NEW.grade
  THEN RAISE EXCEPTION 'Analysis input is immutable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER analysis_input_history BEFORE UPDATE ON ai_tutor_analysisinput
FOR EACH ROW EXECUTE FUNCTION analysis_input_history_guard();

CREATE FUNCTION analysis_feedback_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.text IS DISTINCT FROM NEW.text OR OLD.number IS DISTINCT FROM NEW.number
     OR OLD.kind IS DISTINCT FROM NEW.kind OR OLD.analysis_id IS DISTINCT FROM NEW.analysis_id THEN
    RAISE EXCEPTION 'Feedback history is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER analysis_feedback_history BEFORE UPDATE ON ai_tutor_analysisfeedback
FOR EACH ROW EXECUTE FUNCTION analysis_feedback_history_guard();
"""

OLD_GUARD = importlib.import_module("apps.problems.migrations.0002_scope_guards").FORWARD
REVERSE = """
DROP TRIGGER analysis_feedback_history ON ai_tutor_analysisfeedback;
DROP FUNCTION analysis_feedback_history_guard();
DROP TRIGGER analysis_input_history ON ai_tutor_analysisinput;
DROP FUNCTION analysis_input_history_guard();
DROP TRIGGER analysis_history ON ai_tutor_analysis;
DROP FUNCTION analysis_history_guard();
DROP TRIGGER analysis_input_scope ON ai_tutor_analysisinput;
DROP TRIGGER analysis_result_scope ON ai_tutor_analysis;
DROP FUNCTION analysis_scope_guard();
""" + OLD_GUARD[
    OLD_GUARD.index("CREATE FUNCTION ocr_scope_guard()") : OLD_GUARD.index(
        "CREATE TRIGGER ocr_scope"
    )
].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


class Migration(migrations.Migration):
    dependencies = [
        ("ai_tutor", "0001_initial"),
        ("ocr", "0003_ocrjob_task_type_ocrjob_text_version_and_more"),
    ]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
