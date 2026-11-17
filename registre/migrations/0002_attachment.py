from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("registre", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Attachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("name", models.CharField(max_length=255)),
                ("content_type", models.CharField(max_length=20)),
                ("data", models.BinaryField()),
                ("intervention", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                   related_name="attachments", to="registre.intervention")),
                ("uploader", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                               to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["pk"]},
        ),
    ]
