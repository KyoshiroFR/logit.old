from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from .models import Attachment, Equipment, Intervention, Revision, Service


class RegistreTests(TestCase):
    def test_traceabilite_et_acces(self):
        user_model = get_user_model()
        author = user_model.objects.create_user("karim", password="local-test-only")
        editor = user_model.objects.create_user("lea")
        firewall = Equipment.objects.create(name="Pare-feu")
        dns = Equipment.objects.create(name="DNS")
        vpn = Service.objects.create(name="VPN")
        intranet = Service.objects.create(name="Intranet")

        self.assertRedirects(
            self.client.get("/", secure=True), "/connexion/?next=/", fetch_redirect_response=False,
        )
        self.assertRedirects(
            self.client.post("/connexion/", {"username": "karim", "password": "local-test-only"}, secure=True),
            "/", fetch_redirect_response=False,
        )
        fields = {
            "title": "Règle VPN",
            "occurred_at": "2026-11-17T14:05",
            "equipment": firewall.pk,
            "change": "Désactivation d’un accès temporaire",
            "reason": "Accès expiré",
            "impact": "À vérifier",
            "rollback": "Restaurer l’ancienne règle",
            "verification": "Connexion interne testée",
            "before_state": "État de test initial",
            "after_state": "État de test final",
            "service": vpn.pk,
            "impacted_services": [vpn.pk, intranet.pk],
        }
        response = self.client.post("/interventions/nouvelle/", fields, secure=True)
        item = Intervention.objects.get()
        self.assertEqual(item.author, author)
        self.assertRedirects(response, f"/interventions/{item.pk}/", fetch_redirect_response=False)

        self.client.force_login(editor)
        self.assertEqual(self.client.get("/administration/", secure=True).status_code, 302)
        register = self.client.get("/", secure=True)
        for field in ("q", "equipment", "service", "author", "start", "end"):
            self.assertContains(register, f'id="id_{field}"')
        self.assertNotContains(self.client.get("/", {"equipment": dns.pk}, secure=True), "Règle VPN")
        self.assertContains(self.client.get("/", {"equipment": firewall.pk}, secure=True), "Règle VPN")
        filtered = self.client.get("/", {"service": intranet.pk}, secure=True)
        self.assertEqual(filtered.context["page"].paginator.count, 1)
        self.assertEqual(filtered.context["impact_services"], [intranet, vpn])
        self.assertContains(filtered, 'class="removed"')
        self.assertContains(filtered, 'class="changed"')

        fields["impact"] = "Accès prestataire fermé"
        fields["correction_reason"] = "Vérification terminée"
        response = self.client.post(f"/interventions/{item.pk}/corriger/", fields, secure=True)
        self.assertRedirects(response, f"/interventions/{item.pk}/", fetch_redirect_response=False)
        revision = Revision.objects.get(intervention=item)
        self.assertEqual(revision.editor, editor)
        self.assertEqual(revision.changes["impact"], {"before": "À vérifier", "after": fields["impact"]})
        self.assertContains(self.client.get(f"/interventions/{item.pk}/", secure=True), "À vérifier")

    def test_captures_restent_privees_et_tracables(self):
        member = get_user_model().objects.create_user("lea")
        self.client.force_login(member)
        equipment = Equipment.objects.create(name="Pare-feu")
        item = Intervention.objects.create(
            title="Règle VPN", equipment=equipment, author=member,
            change="Règle modifiée", reason="Maintenance", impact="Interne",
            verification="Connexion testée", rollback="Rétablir la règle",
        )
        fields = {
            "title": item.title, "equipment": equipment.pk,
            "occurred_at": "2026-11-17T14:05",
            "change": item.change, "reason": item.reason, "impact": item.impact,
            "verification": item.verification, "rollback": item.rollback,
            "correction_reason": "Ajout de la preuve",
        }
        edit_url = f"/interventions/{item.pk}/corriger/"
        fields["attachments"] = SimpleUploadedFile("faux.png", b"not an image", content_type="image/png")
        self.assertContains(self.client.post(edit_url, fields, secure=True), "Choisis une image")
        self.assertFalse(Attachment.objects.exists())

        capture = BytesIO()
        Image.new("RGB", (4, 4)).save(capture, format="PNG")
        fields["attachments"] = [
            SimpleUploadedFile(name, capture.getvalue(), content_type="image/png")
            for name in ("capture.png", "capture-2.png")
        ]
        self.assertEqual(self.client.post(edit_url, fields, secure=True).status_code, 302)
        self.assertEqual(Attachment.objects.count(), 2)
        image = Attachment.objects.first()
        self.assertEqual(image.uploader, member)
        self.assertIn("capture.png", Revision.objects.get().changes["captures ajoutées"]["after"])
        self.assertContains(self.client.get(f"/interventions/{item.pk}/", secure=True), "capture.png")
        url = f"/captures/{image.pk}/"
        response = self.client.get(url, secure=True)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response.content, capture.getvalue())
        self.client.logout()
        self.assertEqual(self.client.get(url, secure=True).status_code, 302)
