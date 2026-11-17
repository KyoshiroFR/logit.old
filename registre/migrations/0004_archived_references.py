from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("registre", "0003_intervention_impacted_services")]

    operations = [
        migrations.AddField(
            model_name="equipment", name="archived", field=models.BooleanField("archivé", default=False),
        ),
        migrations.AddField(
            model_name="service", name="archived", field=models.BooleanField("archivé", default=False),
        ),
    ]
