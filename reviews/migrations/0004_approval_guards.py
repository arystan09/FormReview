from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("reviews", "0003_reviewdraft_decisions_reviewdraft_mode_and_more")]
    operations = [
        migrations.RunSQL(
            sql="""
        CREATE OR REPLACE FUNCTION formreview_check_draft_references() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF OLD.status = 'approved' OR NEW.document_id IS DISTINCT FROM OLD.document_id
              OR NEW.run_id IS DISTINCT FROM OLD.run_id
              OR NEW.text_version_id IS DISTINCT FROM OLD.text_version_id OR NEW.mode <> OLD.mode
            THEN RAISE EXCEPTION 'Closed or bound draft cannot be replaced'; END IF;
            IF NOT ((NEW.status = 'active' AND NEW.revision = OLD.revision + 1)
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
        CREATE TRIGGER immutable_review_event BEFORE UPDATE OR DELETE ON reviews_reviewevent
          FOR EACH ROW EXECUTE FUNCTION formreview_reject_source_mutation();
        CREATE TRIGGER immutable_approved_record BEFORE UPDATE OR DELETE ON reviews_approvedrecord
          FOR EACH ROW EXECUTE FUNCTION formreview_reject_source_mutation();
        CREATE TRIGGER immutable_approval_receipt BEFORE UPDATE OR DELETE ON reviews_approvalreceipt
          FOR EACH ROW EXECUTE FUNCTION formreview_reject_source_mutation();
        CREATE FUNCTION formreview_check_approval_references() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_TABLE_NAME = 'reviews_approvedrecord' THEN
            IF NOT EXISTS (SELECT 1 FROM reviews_reviewdraft
              WHERE id = NEW.draft_id AND document_id = NEW.document_id AND status = 'active')
            THEN RAISE EXCEPTION 'Approval draft mismatch'; END IF;
          ELSE
            IF NOT EXISTS (SELECT 1 FROM reviews_approvedrecord r JOIN documents_document d
              ON d.id = r.document_id WHERE r.id = NEW.record_id
              AND d.workspace_id = NEW.workspace_id)
            THEN RAISE EXCEPTION 'Approval receipt workspace mismatch'; END IF;
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER approval_record_reference BEFORE INSERT ON reviews_approvedrecord
          FOR EACH ROW EXECUTE FUNCTION formreview_check_approval_references();
        CREATE TRIGGER approval_receipt_reference BEFORE INSERT ON reviews_approvalreceipt
          FOR EACH ROW EXECUTE FUNCTION formreview_check_approval_references();
        """,
            # Reversing this boundary requires an explicit data/schema downgrade plan.
        )
    ]
