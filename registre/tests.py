from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from PIL import Image

from .models import Attachment, Equipment, Intervention, Revision, Service
from .views import configuration_lines


class RegistreTests(TestCase):
    def test_administration_preserve_les_references_et_les_auteurs(self):
        users = get_user_model()
        admin = users.objects.create_superuser("admin")
        staff = users.objects.create_user("staff", is_staff=True)
        author = users.objects.create_user("auteur")
        equipment = Equipment.objects.create(name="Pare-feu historique")
        service = Service.objects.create(name="VPN satellite")
        item = Intervention.objects.create(title="Intervention historique", equipment=equipment, author=author)
        item.impacted_services.add(service)
        event = LogEntry.objects.create(user=author, object_repr=service.name, action_flag=CHANGE)
        self.client.force_login(admin)
        for path in (
            f"auth/user/{author.pk}/delete/",
            f"registre/equipment/{equipment.pk}/delete/",
            f"registre/service/{service.pk}/delete/",
        ):
            self.assertEqual(self.client.post("/administration/" + path, {"post": "yes"}, secure=True).status_code, 403)
        self.assertTrue(item.impacted_services.filter(pk=service.pk).exists())
        author.is_active = False
        author.save(update_fields=["is_active"])
        self.assertTrue(LogEntry.objects.filter(pk=event.pk, user=author).exists())
        self.assertContains(self.client.get("/administration/journal/", {"author": author.pk}, secure=True), service.name)
        self.assertContains(self.client.get(f"/interventions/{item.pk}/", secure=True), author.username)
        staff.user_permissions.add(*Permission.objects.filter(codename__in=["change_user", "change_group", "view_service"]))
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/administration/auth/user/", secure=True).status_code, 403)
        self.assertEqual(self.client.get("/administration/auth/group/", secure=True).status_code, 403)
        self.assertEqual(self.client.get("/administration/registre/service/", secure=True).status_code, 200)
        self.assertEqual(self.client.get("/administration/journal/", secure=True).status_code, 403)
        self.client.force_login(author)
        self.assertEqual(self.client.get("/historique/", secure=True).status_code, 302)

    def test_recherche_reference_equipement_et_services_sans_doublons(self):
        member = get_user_model().objects.create_user("membre")
        equipment = Equipment.objects.create(name="Pare-feu test")
        services = [Service.objects.create(name=name) for name in ("VPN principal", "VPN nomades", "VPN partenaires")]
        item = Intervention.objects.create(
            title="Ajustement réseau", equipment=equipment, author=member,
            reference="FW-9087", service=services[0],
        )
        item.impacted_services.set(services[1:])
        self.client.force_login(member)
        for term in ("FW-9087", "Pare-feu test", "VPN principal", "VPN nomades", "VPN"):
            response = self.client.get("/historique/", {"q": term}, secure=True)
            self.assertEqual(list(response.context["page"]), [item])

    def test_archivage_reactivation_et_journal_admin(self):
        users = get_user_model()
        admin = users.objects.create_superuser("admin")
        staff = users.objects.create_user("staff", is_staff=True)
        self.client.force_login(admin)
        equipment = Equipment.objects.create(name="Pare-feu historique")
        service = Service.objects.create(name="VPN historique")
        item = Intervention.objects.create(title="Intervention historique", equipment=equipment, service=service, author=admin)
        item.impacted_services.add(service)
        references = (("equipment", equipment), ("service", service))
        for model, reference in references:
            path = f"/administration/registre/{model}/"
            self.assertEqual(self.client.post(path, {"action": "archive", "_selected_action": reference.pk, "index": 0}, secure=True).status_code, 302)
            reference.refresh_from_db()
            self.assertTrue(reference.archived)
        creation = self.client.get("/interventions/nouvelle/", secure=True).context["form"]
        self.assertFalse(creation.fields["equipment"].queryset.exists())
        self.assertFalse(creation.fields["service"].queryset.exists())
        self.assertFalse(creation.fields["impacted_services"].queryset.exists())
        correction = self.client.get(f"/interventions/{item.pk}/corriger/", secure=True).context["form"]
        self.assertEqual(list(correction.fields["equipment"].queryset), [equipment])
        self.assertEqual(list(correction.fields["service"].queryset), [service])
        self.assertEqual(list(correction.fields["impacted_services"].queryset), [service])
        self.assertContains(self.client.get("/historique/", {"equipment": equipment.pk}, secure=True), item.title)
        journal = "/administration/journal/"
        today = timezone.localdate()
        other_entry = LogEntry.objects.create(
            user=staff, object_repr="Autre auteur", action_flag=CHANGE,
            content_type=ContentType.objects.get_for_model(Equipment),
        )
        LogEntry.objects.filter(pk=other_entry.pk).update(action_time=timezone.now() - timedelta(days=2))
        response = self.client.get(journal, {"author": admin.pk, "start": today, "end": today}, secure=True)
        self.assertContains(response, "2 actions")
        self.assertContains(response, "Archivage", count=2)
        self.assertNotContains(response, "Autre auteur")
        self.assertContains(self.client.get(journal, {"author": staff.pk}, secure=True), "Autre auteur")
        for model, reference in references:
            path = f"/administration/registre/{model}/"
            self.assertEqual(self.client.post(path, {"action": "restore", "_selected_action": reference.pk, "index": 0}, secure=True).status_code, 302)
            reference.refresh_from_db()
            self.assertFalse(reference.archived)
        self.assertContains(self.client.get(journal, secure=True), "Réactivation", count=2)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(journal, secure=True).status_code, 403)

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
