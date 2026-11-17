from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("registre", "0002_attachment")]

    operations = [
        migrations.AddField(model_name="intervention", name="before_state", field=models.TextField(blank=True, verbose_name="état avant")),
        migrations.AddField(model_name="intervention", name="after_state", field=models.TextField(blank=True, verbose_name="état après")),
        migrations.AddField(
            model_name="intervention",
            name="impacted_services",
            field=models.ManyToManyField(
                blank=True, related_name="impacting_interventions", to="registre.service", verbose_name="services concernés",
            ),
        ),
    ]
