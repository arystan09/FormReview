from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql="""
            CREATE FUNCTION formreview_reject_source_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'Canonical sources and document metadata are immutable';
            END;
            $$;
            CREATE TRIGGER immutable_document BEFORE UPDATE OR DELETE ON documents_document
              FOR EACH ROW EXECUTE FUNCTION formreview_reject_source_mutation();
            CREATE TRIGGER immutable_text BEFORE UPDATE OR DELETE ON documents_textversion
              FOR EACH ROW EXECUTE FUNCTION formreview_reject_source_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER immutable_text ON documents_textversion;
            DROP TRIGGER immutable_document ON documents_document;
            DROP FUNCTION formreview_reject_source_mutation();
            """,
        ),
    ]
