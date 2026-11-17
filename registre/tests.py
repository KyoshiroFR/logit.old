from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from .models import Attachment, Equipment, Intervention, Revision, Service
from .views import configuration_lines


class RegistreTests(TestCase):
    def test_diff_conserve_les_lignes_et_leurs_numeros(self):
        old = [f'ligne "{number}"' for number in range(1, 41)]
        new = old.copy()
        new[19:20] = ['valeur "<balise>"', "ligne ajoutée"]
        before, after = configuration_lines("\n".join(old), "\n".join(new))
        self.assertEqual(len(before), 40)
        self.assertEqual(len(after), 42)
        self.assertEqual(after[19], (20, "-", ["ligne ", '"20"', ""]))
        self.assertEqual(after[20], (20, "+", ["valeur ", '"<balise>"', ""]))
        self.assertEqual(after[-1][0], 41)

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
        self.assertNotContains(self.client.get("/historique/", {"equipment": dns.pk}, secure=True), "Règle VPN")
        self.assertContains(self.client.get("/historique/", {"equipment": firewall.pk}, secure=True), "Règle VPN")
        filtered = self.client.get("/historique/", {"service": intranet.pk}, secure=True)
        self.assertEqual(filtered.context["page"].paginator.count, 1)
        detail = self.client.get(f"/interventions/{item.pk}/", secure=True)
        self.assertEqual(detail.context["impact_services"], [intranet, vpn])
        self.assertContains(detail, 'class="removed"')
        self.assertContains(detail, 'class="changed"')

        fields["impact"] = "Accès prestataire fermé"
        fields["correction_reason"] = "Vérification terminée"
        response = self.client.post(f"/interventions/{item.pk}/corriger/", fields, secure=True)
        self.assertRedirects(response, f"/interventions/{item.pk}/", fetch_redirect_response=False)
        revision = Revision.objects.get(intervention=item)
        self.assertEqual(revision.editor, editor)
        self.assertEqual(revision.changes["impact"], {"before": "À vérifier", "after": fields["impact"]})
        self.assertContains(self.client.get(f"/interventions/{item.pk}/", secure=True), "À vérifier")

    def test_historique_filtre_pagine_et_retour(self):
        member = get_user_model().objects.create_user("lea")
        firewall = Equipment.objects.create(name="Pare-feu")
        self.client.force_login(member)
        Intervention.objects.bulk_create([
            Intervention(title=f"VPN {index:02}", equipment=firewall, author=member)
            for index in range(50)
        ])
        Intervention.objects.create(title="DNS", equipment=firewall, author=member)
        filters = {"q": "VPN", "equipment": firewall.pk}
        history = "/historique/"
        for number, count in ((1, 20), (2, 20), (3, 10)):
            response = self.client.get(history, {**filters, "page": number}, secure=True)
            page = response.context["page"]
            self.assertEqual(page.paginator.count, 50)
            self.assertEqual(len(page.object_list), count)
            self.assertEqual(page.number, number)
        second = self.client.get(history, {**filters, "page": 2}, secure=True)
        self.assertEqual(second.context["page"].object_list[0].title, "VPN 29")
        item = second.context["page"].object_list[0]
        self.assertContains(second, f'href="/historique/?equipment={firewall.pk}"')
        detail = self.client.get(f"/interventions/{item.pk}/", {**filters, "page": 2, "from": "history"}, secure=True)
        self.assertContains(detail, f'href="/historique/?q=VPN&amp;equipment={firewall.pk}&amp;page=2"')
        self.assertContains(detail, "Retour aux résultats")
        self.assertEqual(len(self.client.get("/", secure=True).context["recent"]), 5)

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
