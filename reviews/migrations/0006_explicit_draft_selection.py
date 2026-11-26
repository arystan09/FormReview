from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("reviews", "0005_alter_reviewdraft_document_and_more")]
    operations = [
        migrations.RunSQL(
            """
        CREATE OR REPLACE FUNCTION formreview_check_draft_references() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF OLD.status <> 'active' OR NEW.document_id IS DISTINCT FROM OLD.document_id
              OR NEW.run_id IS DISTINCT FROM OLD.run_id
              OR NEW.text_version_id IS DISTINCT FROM OLD.text_version_id OR NEW.mode <> OLD.mode
            THEN RAISE EXCEPTION 'Closed or bound draft cannot be replaced'; END IF;
            IF NOT ((NEW.status = 'active' AND NEW.revision = OLD.revision + 1)
              OR (NEW.status = 'superseded' AND NEW.revision = OLD.revision + 1
                  AND NEW.decisions = OLD.decisions)
              OR (NEW.status = 'approved' AND NEW.revision = OLD.revision
                  AND NEW.decisions = OLD.decisions))
            THEN RAISE EXCEPTION 'Invalid draft revision transition'; END IF;
          END IF;
          IF NEW.mode = 'manual' AND NEW.run_id IS NULL THEN
            IF NOT EXISTS (SELECT 1 FROM documents_textversion
              WHERE id = NEW.text_version_id AND document_id = NEW.document_id)
            THEN RAISE EXCEPTION 'Manual draft source mismatch'; END IF;
          ELSE
            IF NOT EXISTS (SELECT 1 FROM extraction_extractionrun r
              JOIN documents_textversion t ON t.id = r.text_version_id
              WHERE r.id = NEW.run_id AND r.status = 'validated' AND r.mode = NEW.mode
              AND t.id = NEW.text_version_id AND t.document_id = NEW.document_id)
            THEN RAISE EXCEPTION 'Draft source/run mismatch'; END IF;
          END IF;
          RETURN NEW;
        END; $$;
"""
        )
    ]
