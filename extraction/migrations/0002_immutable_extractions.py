from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("extraction", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql="""
        CREATE TRIGGER immutable_extraction_config
          BEFORE UPDATE OR DELETE ON extraction_extractionconfig
          FOR EACH ROW EXECUTE FUNCTION formreview_reject_source_mutation();
        CREATE TRIGGER immutable_extraction_run
          BEFORE UPDATE OR DELETE ON extraction_extractionrun
          FOR EACH ROW EXECUTE FUNCTION formreview_reject_source_mutation();
        CREATE TRIGGER immutable_field_candidate
          BEFORE UPDATE OR DELETE ON extraction_fieldcandidate
          FOR EACH ROW EXECUTE FUNCTION formreview_reject_source_mutation();
        CREATE FUNCTION formreview_check_run_references() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.config_hash IS DISTINCT FROM
              (SELECT config_hash FROM extraction_extractionconfig WHERE id = NEW.config_id)
             OR NEW.canonical_sha256 IS DISTINCT FROM
              (SELECT canonical_sha256 FROM documents_textversion WHERE id = NEW.text_version_id)
          THEN RAISE EXCEPTION 'Extraction reference hash mismatch'; END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER check_run_references BEFORE INSERT ON extraction_extractionrun
          FOR EACH ROW EXECUTE FUNCTION formreview_check_run_references();
        """,
            reverse_sql="""
        DROP TRIGGER check_run_references ON extraction_extractionrun;
        DROP FUNCTION formreview_check_run_references();
        DROP TRIGGER immutable_field_candidate ON extraction_fieldcandidate;
        DROP TRIGGER immutable_extraction_run ON extraction_extractionrun;
        DROP TRIGGER immutable_extraction_config ON extraction_extractionconfig;
        """,
        )
    ]
