from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse


class BootstrapAdminTests(TestCase):
    def test_creates_a_superuser_with_temporary_password_once(self):
        output = StringIO()
        call_command("bootstrap_admin", stdout=output)
        identifier, credentials = output.getvalue().splitlines()
        self.assertEqual(identifier, "Identifiant admin-logit")
        self.assertTrue(credentials.startswith("Mot de passe temporaire "))
        password = credentials.removeprefix("Mot de passe temporaire ")
        self.assertEqual(len(password), 32)

        admin = get_user_model().objects.get(username="admin-logit")
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.accountsecurity.must_change_password)
        self.assertTrue(admin.check_password(password))

        response = self.client.post(reverse("login"), {"username": admin.username, "password": password}, secure=True)
        self.assertRedirects(response, reverse("first_password"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("admin:index"), secure=True).status_code, 302)

        repeated = StringIO()
        call_command("bootstrap_admin", stdout=repeated)
        self.assertNotIn("Mot de passe temporaire", repeated.getvalue())
        admin.refresh_from_db()
        self.assertTrue(admin.check_password(password))

    def test_leaves_a_database_with_an_existing_member_alone(self):
        member = get_user_model().objects.create_user("lea")
        output = StringIO()
        call_command("bootstrap_admin", stdout=output)
        self.assertIn("Aucun compte créé", output.getvalue())
        self.assertEqual(list(get_user_model().objects.all()), [member])
