from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("extraction", "0003_liveallowance_liveattempt_and_more")]
    operations = [
        migrations.RunSQL(
            sql="""
    CREATE TRIGGER retain_live_allowance BEFORE DELETE ON extraction_liveallowance
      FOR EACH ROW EXECUTE FUNCTION formreview_reject_source_mutation();
    CREATE TRIGGER retain_live_attempt BEFORE DELETE ON extraction_liveattempt
      FOR EACH ROW EXECUTE FUNCTION formreview_reject_source_mutation();
    CREATE FUNCTION formreview_live_allowance_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.consumed < OLD.consumed THEN
        RAISE EXCEPTION 'Consumed requests cannot be replenished';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER live_allowance_guard BEFORE UPDATE ON extraction_liveallowance
      FOR EACH ROW EXECUTE FUNCTION formreview_live_allowance_guard();
    CREATE FUNCTION formreview_live_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.config_id <> OLD.config_id OR NEW.text_version_id <> OLD.text_version_id
        OR NEW.requested_by_id <> OLD.requested_by_id OR NEW.request_hash <> OLD.request_hash
        OR NEW.allowance_version <> OLD.allowance_version
        OR NEW.price_snapshot <> OLD.price_snapshot
        OR NEW.estimate_usd <> OLD.estimate_usd
      THEN RAISE EXCEPTION 'Live admission snapshot is immutable'; END IF;
      IF NOT ((OLD.status = 'queued' AND NEW.status IN ('submitted', 'cancelled'))
        OR (OLD.status = 'submitted' AND NEW.status IN ('done', 'unknown'))
        OR (OLD.status = 'unknown' AND NEW.status = 'unknown'))
      THEN RAISE EXCEPTION 'Live attempts cannot be retried'; END IF;
      IF OLD.run_id IS NOT NULL AND NEW.run_id IS DISTINCT FROM OLD.run_id THEN
        RAISE EXCEPTION 'Live result is immutable'; END IF;
      IF NEW.run_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM extraction_extractionrun WHERE id = NEW.run_id
        AND text_version_id = NEW.text_version_id AND config_id = NEW.config_id
        AND mode = 'live' AND request_hash = NEW.request_hash)
      THEN RAISE EXCEPTION 'Live result reference mismatch'; END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER live_attempt_guard BEFORE UPDATE ON extraction_liveattempt
      FOR EACH ROW EXECUTE FUNCTION formreview_live_attempt_guard();
    """
        )
    ]
