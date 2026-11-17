import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import hotp
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import AccountSecurity, Equipment, Service


class AccountRecoveryTests(TestCase):
    def verify_device(self, device, target):
        timestep = int((time.time() - device.t0) // device.step)
        code = str(hotp(device.bin_key, timestep, digits=device.digits)).zfill(device.digits)
        response = self.client.post(reverse("totp"), {"code": code}, secure=True)
        self.assertRedirects(response, target, fetch_redirect_response=False)

    def test_totp_recovery_revokes_session_and_requires_reenrollment(self):
        password = "Equipe_Recette4!Arome"
        member = get_user_model().objects.create_user("membre-reenrolement", password=password)
        policy = AccountSecurity.objects.create(user=member, totp_required=True)
        old_device = TOTPDevice.objects.create(user=member, name="LogIT", confirmed=True)
        old_key = old_device.key
        credentials = {"username": member.username, "password": password}
        login_url = reverse("login")
        totp_url = reverse("totp")
        history_url = reverse("history")

        self.assertRedirects(self.client.post(login_url, credentials, secure=True), totp_url, fetch_redirect_response=False)
        self.assertNotContains(self.client.get(totp_url, secure=True), "QR code")
        self.verify_device(old_device, reverse("index"))
        self.assertEqual(self.client.get(history_url, secure=True).status_code, 200)

        # Rejoue la suppression locale de l’appareil après vérification d’identité.
        TOTPDevice.objects.filter(user=member).delete()
        policy.refresh_from_db()
        self.assertTrue(policy.totp_required)
        self.assertEqual(self.client.get(history_url, secure=True).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(self.client.get(totp_url, secure=True), login_url, fetch_redirect_response=False)

        self.assertRedirects(self.client.post(login_url, credentials, secure=True), totp_url, fetch_redirect_response=False)
        self.assertContains(self.client.get(totp_url, secure=True), "QR code")
        replacement = TOTPDevice.objects.get(user=member)
        self.assertFalse(replacement.confirmed)
        self.assertNotEqual(replacement.key, old_key)
        self.assertEqual(self.client.get(history_url, secure=True).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.verify_device(replacement, reverse("index"))
        replacement.refresh_from_db()
        self.assertTrue(replacement.confirmed)
        self.assertEqual(self.client.get(history_url, secure=True).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:index"), secure=True).status_code, 302)


class AdminAuditPresentationTests(TestCase):
    def test_journal_identifies_archive_states_object_author_and_date(self):
        users = get_user_model()
        admin = users.objects.create_superuser("super-journal")
        staff = users.objects.create_user("equipe-journal", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="change_service"))
        equipment = Equipment.objects.create(name="Pare-feu recette")
        service = Service.objects.create(name="Service recette")
        self.client.force_login(staff)
        service_list = reverse("admin:registre_service_changelist")
        self.assertEqual(self.client.post(service_list, {
            "action": "archive", "_selected_action": service.pk, "index": 0,
        }, secure=True).status_code, 302)

        self.client.force_login(admin)
        equipment_form = reverse("admin:registre_equipment_change", args=[equipment.pk])
        self.assertEqual(self.client.post(equipment_form, {
            "name": equipment.name, "archived": "on", "_save": "Enregistrer",
        }, secure=True).status_code, 302)
        self.assertEqual(self.client.post(service_list, {
            "action": "restore", "_selected_action": service.pk, "index": 0,
        }, secure=True).status_code, 302)
        journal = reverse("admin_audit")
        response = self.client.get(journal, secure=True)
        self.assertContains(response, '<span class="audit-action audit-archive">Archivage</span>', count=2, html=True)
        self.assertContains(response, '<span class="audit-action audit-restore">Réactivation</span>', count=1, html=True)
        self.assertContains(response, '<th scope="col">Auteur</th>', html=True)
        self.assertContains(response, '<th scope="col">Date et heure</th>', html=True)
        self.assertContains(response, equipment.name)
        self.assertContains(response, service.name)

        day = timezone.localdate()
        staff_filters = {"author": staff.pk, "start": day, "end": day}
        response = self.client.get(journal, staff_filters, secure=True)
        self.assertContains(response, service.name)
        self.assertNotContains(response, equipment.name)
        self.assertNotContains(response, "Réactivation")
        self.assertContains(response, '<time datetime="', count=1)
        staff_filters["start"] = staff_filters["end"] = day - timedelta(days=1)
        self.assertContains(self.client.get(journal, staff_filters, secure=True), "Aucune action pour ces critères.")
