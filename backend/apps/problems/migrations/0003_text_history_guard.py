from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("problems", "0002_scope_guards")]
    operations = [
        migrations.RunSQL(
            """
        CREATE FUNCTION text_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_problem uuid;
        BEGIN
          IF TG_OP='UPDATE' AND (
            OLD.problem_id IS DISTINCT FROM NEW.problem_id OR
            OLD.number IS DISTINCT FROM NEW.number OR OLD.origin IS DISTINCT FROM NEW.origin OR
            OLD.text IS DISTINCT FROM NEW.text OR OLD.answer IS DISTINCT FROM NEW.answer OR
            OLD.confirmed IS DISTINCT FROM NEW.confirmed OR
            OLD.ocr_job_id IS DISTINCT FROM NEW.ocr_job_id OR
            OLD.confidence IS DISTINCT FROM NEW.confidence OR
            OLD.uncertainties IS DISTINCT FROM NEW.uncertainties OR
            (NEW.parent_id IS NOT NULL AND OLD.parent_id IS DISTINCT FROM NEW.parent_id)
          ) THEN
            RAISE EXCEPTION 'Text history is immutable' USING ERRCODE='23514';
          END IF;
          IF NEW.parent_id IS NOT NULL THEN
            SELECT problem_id INTO parent_problem FROM problems_problemtextversion
              WHERE id=NEW.parent_id;
            IF parent_problem IS DISTINCT FROM NEW.problem_id THEN
              RAISE EXCEPTION 'Text parent scope mismatch' USING ERRCODE='23514';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER text_history BEFORE INSERT OR UPDATE ON problems_problemtextversion
        FOR EACH ROW EXECUTE FUNCTION text_history_guard();
        """,
            "DROP TRIGGER text_history ON problems_problemtextversion; "
            "DROP FUNCTION text_history_guard();",
        )
    ]
