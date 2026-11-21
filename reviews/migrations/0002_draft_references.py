from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("reviews", "0001_initial"), ("extraction", "0002_immutable_extractions")]
    operations = [
        migrations.RunSQL(
            sql="""
        CREATE FUNCTION formreview_check_draft_references() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM extraction_extractionrun r JOIN documents_textversion t
            ON t.id = r.text_version_id WHERE r.id = NEW.run_id
            AND r.status = 'validated' AND t.id = NEW.text_version_id
            AND t.document_id = NEW.document_id
          ) THEN RAISE EXCEPTION 'Draft source/run mismatch'; END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER check_draft_references BEFORE INSERT OR UPDATE ON reviews_reviewdraft
          FOR EACH ROW EXECUTE FUNCTION formreview_check_draft_references();
        """,
            reverse_sql="""
        DROP TRIGGER check_draft_references ON reviews_reviewdraft;
        DROP FUNCTION formreview_check_draft_references();
        """,
        )
    ]
