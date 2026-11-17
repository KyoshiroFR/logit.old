from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Equipment, Intervention, Revision


class RegistreTests(TestCase):
    def test_traceabilite_et_acces(self):
        user_model = get_user_model()
        author = user_model.objects.create_user("karim", password="local-test-only")
        editor = user_model.objects.create_user("lea")
        firewall = Equipment.objects.create(name="Pare-feu")
        dns = Equipment.objects.create(name="DNS")

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
        }
        response = self.client.post("/interventions/nouvelle/", fields, secure=True)
        item = Intervention.objects.get()
        self.assertEqual(item.author, author)
        self.assertRedirects(response, f"/interventions/{item.pk}/", fetch_redirect_response=False)

        self.client.force_login(editor)
        self.assertEqual(self.client.get("/administration/", secure=True).status_code, 302)
        self.assertNotContains(self.client.get("/", {"equipment": dns.pk}, secure=True), "Règle VPN")
        self.assertContains(self.client.get("/", {"equipment": firewall.pk}, secure=True), "Règle VPN")

        fields["impact"] = "Accès prestataire fermé"
        fields["correction_reason"] = "Vérification terminée"
        response = self.client.post(f"/interventions/{item.pk}/corriger/", fields, secure=True)
        self.assertRedirects(response, f"/interventions/{item.pk}/", fetch_redirect_response=False)
        revision = Revision.objects.get(intervention=item)
        self.assertEqual(revision.editor, editor)
        self.assertEqual(revision.changes["impact"], {"before": "À vérifier", "after": fields["impact"]})
        self.assertContains(self.client.get(f"/interventions/{item.pk}/", secure=True), "À vérifier")
