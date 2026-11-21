from datetime import timedelta

import pyotp
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from .chain import record_event, verify
from .models import AuditEvent, Element, Intervention, Profile, Version
from .permissions import CONTRIBUTOR, READER

User = get_user_model()
FMT = "%Y-%m-%dT%H:%M"


def make_user(username, role="contributor", password="motdepasse-solide-42", **profile):
    user = User.objects.create_user(username, password=password, is_superuser=role == "admin")
    if role != "admin":
        user.groups.add(Group.objects.get(name=CONTRIBUTOR if role == "contributor" else READER))
    Profile.objects.create(user=user, must_change_password=profile.pop("must_change_password", False), **profile)
    return user


class Base(TestCase):
    def setUp(self):
        self.firewall = Element.objects.create(name="FW-01", kind=Element.EQUIPMENT)
        self.vpn = Element.objects.create(name="VPN", kind=Element.SERVICE)
        self.alice = make_user("alice")
        self.client.force_login(self.alice)

    def fiche(self, **overrides):
        data = {"kind": "normal", "title": "Ouverture port 443 vers DMZ",
                "occurred_at": timezone.localtime().strftime(FMT), "elements": [self.firewall.pk, self.vpn.pk],
                "change": "Ajout règle 42", "reason": "Demande n° 1234", "impact": "Aucun",
                "verification": "Test de connexion OK", "rollback": "Supprimer la règle 42",
                "before_state": "rule 41 allow\n", "after_state": "rule 41 allow\nrule 42 allow 443\n"}
        data.update(overrides)
        return data

    def post(self, url, data):
        return self.client.post(url, data, secure=True)

    def get(self, url, **params):
        return self.client.get(url, params, secure=True)


class InterventionTests(Base):
    def test_horodatage_serveur_ignore_les_valeurs_envoyees(self):
        before = timezone.now()
        response = self.post("/fiches/nouvelle/", self.fiche(recorded_at="2001-01-01T00:00"))
        intervention = Intervention.objects.get()
        self.assertRedirects(response, f"/fiches/{intervention.pk}/", fetch_redirect_response=False)
        version = intervention.current
        self.assertGreaterEqual(intervention.recorded_at, before)
        self.assertGreaterEqual(version.recorded_at, intervention.recorded_at)
        self.assertEqual(version.author, self.alice)
        self.assertEqual(version.status, Version.STATUS_DONE)
        self.assertEqual(sorted(e.name for e in version.elements.all()), ["FW-01", "VPN"])
        self.assertEqual(verify(), [])
        page = self.get(f"/fiches/{intervention.pk}/")
        self.assertContains(page, "serveur, non modifiable")
        self.assertContains(page, "Supprimer la règle 42")
        self.assertContains(page, 'class="added">rule 42 allow 443')

    def test_champs_obligatoires_sauf_urgence(self):
        response = self.post("/fiches/nouvelle/", self.fiche(reason="", rollback=""))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Intervention.objects.exists())
        self.post("/fiches/nouvelle/", self.fiche(kind="urgent", reason="", impact="", verification="", rollback=""))
        version = Intervention.objects.get().current
        self.assertTrue(version.incomplete)
        self.assertContains(self.get("/"), "À compléter")

    def test_date_future_reservee_aux_planifiees(self):
        future = (timezone.localtime() + timedelta(days=2)).strftime(FMT)
        self.assertEqual(self.post("/fiches/nouvelle/", self.fiche(occurred_at=future)).status_code, 200)
        self.post("/fiches/nouvelle/", self.fiche(kind="planned", occurred_at=future))
        version = Intervention.objects.get().current
        self.assertEqual(version.status, Version.STATUS_PLANNED)
        self.assertContains(self.get("/"), "À venir")

    def test_saisie_a_posteriori_signalee(self):
        late = (timezone.localtime() - timedelta(hours=6)).strftime(FMT)
        self.post("/fiches/nouvelle/", self.fiche(occurred_at=late))
        pk = Intervention.objects.get().pk
        self.assertContains(self.get(f"/fiches/{pk}/"), "Saisie a posteriori")
        self.post("/fiches/nouvelle/", self.fiche())
        self.assertNotContains(self.get(f"/fiches/{pk + 1}/"), "Saisie a posteriori")

    def test_correction_cree_une_version_et_garde_l_originale(self):
        self.post("/fiches/nouvelle/", self.fiche())
        intervention = Intervention.objects.get()
        url = f"/fiches/{intervention.pk}/corriger/"
        self.assertEqual(self.post(url, self.fiche(rollback="Restaurer la sauvegarde")).status_code, 200)  # motif manquant
        self.assertContains(self.post(url, self.fiche(note="rien")), "Aucune modification")
        bob = make_user("bob")
        self.client.force_login(bob)
        self.post(url, self.fiche(rollback="Restaurer la sauvegarde de config", note="Procédure précisée"))
        versions = list(intervention.versions.order_by("number"))
        self.assertEqual([v.number for v in versions], [1, 2])
        self.assertEqual(versions[0].rollback, "Supprimer la règle 42")
        self.assertEqual((versions[1].author, versions[1].action), (bob, Version.CORRECTED))
        page = self.get(f"/fiches/{intervention.pk}/")
        self.assertContains(page, "Corrigée</dt><dd>1 fois")
        self.assertContains(page, "Procédure précisée")
        self.assertContains(page, "L’impact ou le retour arrière de cette fiche a été corrigé")
        self.assertEqual(verify(), [])

    def test_planifiee_puis_realisee_et_annulation(self):
        future = (timezone.localtime() + timedelta(hours=3)).strftime(FMT)
        self.post("/fiches/nouvelle/", self.fiche(kind="planned", occurred_at=future))
        pk = Intervention.objects.get().pk
        self.post(f"/fiches/{pk}/realisee/", {"occurred_at": timezone.localtime().strftime(FMT),
                                             "verification": "OK après bascule", "note": ""})
        current = Intervention.objects.get().current
        self.assertEqual((current.status, current.action, current.number), (Version.STATUS_DONE, Version.COMPLETED, 2))
        self.post(f"/fiches/{pk}/annuler/", {"note": "Créée par erreur"})
        current = Intervention.objects.get().current
        self.assertEqual((current.status, current.number), (Version.STATUS_CANCELLED, 3))
        self.assertRedirects(self.get(f"/fiches/{pk}/corriger/"), f"/fiches/{pk}/", fetch_redirect_response=False)
        self.assertContains(self.get("/"), "Annulée")

    def test_recherche_et_filtres(self):
        self.post("/fiches/nouvelle/", self.fiche(title="Règle NAT", elements=[self.firewall.pk]))
        self.post("/fiches/nouvelle/", self.fiche(title="Certificat VPN", elements=[self.vpn.pk], change="Renouvellement"))
        self.assertContains(self.get("/", q="renouvellement"), "Certificat VPN")
        self.assertNotContains(self.get("/", q="renouvellement"), "Règle NAT")
        self.assertNotContains(self.get("/", element=self.vpn.pk), "Règle NAT")
        self.assertEqual(self.get("/", period="24h").context["page"].paginator.count, 2)

    def test_lecteur_consulte_sans_modifier(self):
        self.post("/fiches/nouvelle/", self.fiche())
        pk = Intervention.objects.get().pk
        self.client.force_login(make_user("rsi", role="reader"))
        self.assertEqual(self.get(f"/fiches/{pk}/").status_code, 200)
        for url in ("/fiches/nouvelle/", f"/fiches/{pk}/corriger/", f"/fiches/{pk}/annuler/"):
            self.assertEqual(self.get(url).status_code, 403)
            self.assertEqual(self.post(url, self.fiche(note="x")).status_code, 403)
        self.assertEqual(self.get("/admin/comptes/").status_code, 403)
        self.assertEqual(Version.objects.count(), 1)


class DatabaseProtectionTests(Base):
    def test_la_base_refuse_modification_et_suppression(self):
        self.post("/fiches/nouvelle/", self.fiche())
        record_event("test")
        for statement in ("UPDATE journal_version SET title = 'falsifié'", "DELETE FROM journal_version",
                          "DELETE FROM journal_version_elements", "UPDATE journal_intervention SET recorded_at = now()",
                          "DELETE FROM journal_auditevent", "TRUNCATE journal_version CASCADE"):
            with self.subTest(statement), self.assertRaises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(statement)

    def test_le_compte_application_n_a_pas_les_droits(self):
        call_command("secure_db", stdout=open("/dev/null", "w"))
        self.post("/fiches/nouvelle/", self.fiche())
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL ROLE logit_app")
                cursor.execute("SELECT count(*) FROM journal_version")
                self.assertEqual(cursor.fetchone()[0], 1)
                for statement in ("UPDATE journal_version SET title = 'x'", "DELETE FROM journal_auditevent"):
                    with self.subTest(statement), self.assertRaises(DatabaseError), transaction.atomic():
                        cursor.execute(statement)

    def test_la_chaine_revele_une_falsification(self):
        self.post("/fiches/nouvelle/", self.fiche())
        self.post("/fiches/nouvelle/", self.fiche(title="Deuxième"))
        self.assertEqual(verify(), [])
        with connection.cursor() as cursor:  # un superutilisateur contourne les déclencheurs…
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE journal_version DISABLE TRIGGER journal_version_append_only")
            cursor.execute("UPDATE journal_version SET impact = 'falsifié' WHERE number = 1 AND title = 'Deuxième'")
            cursor.execute("ALTER TABLE journal_version ENABLE TRIGGER journal_version_append_only")
        problems = verify()  # … mais la chaîne d'empreintes le révèle
        self.assertEqual(len(problems), 1)
        self.assertIn("contenu altéré", problems[0])


@override_settings(LOGIT_LOCKOUT_ATTEMPTS=3)
class AuthenticationTests(TestCase):
    def login(self, username, password):
        return self.client.post("/connexion/", {"username": username, "password": password}, secure=True)

    def test_verrouillage_apres_echecs(self):
        make_user("carole")
        for _ in range(3):
            self.assertContains(self.login("carole", "mauvais"), "Identifiant ou mot de passe incorrect")
        response = self.login("carole", "motdepasse-solide-42")
        self.assertContains(response, "temporairement verrouillé")
        self.assertTrue(AuditEvent.objects.filter(action="account_locked", target="carole").exists())
        Profile.objects.filter(user__username="carole").update(locked_until=timezone.now() - timedelta(seconds=1))
        self.assertRedirects(self.login("carole", "motdepasse-solide-42"), "/", fetch_redirect_response=False)

    def test_mot_de_passe_initial_puis_enrolement_totp_obligatoire(self):
        make_user("dan", must_change_password=True, totp_required=True)
        self.login("dan", "motdepasse-solide-42")
        self.assertRedirects(self.client.get("/", secure=True), "/connexion/mot-de-passe/", fetch_redirect_response=False)
        self.client.post("/connexion/mot-de-passe/", {"new_password1": "Nouveau-secret-2026!", "new_password2": "Nouveau-secret-2026!"}, secure=True)
        self.assertRedirects(self.client.get("/", secure=True), "/compte/totp/", fetch_redirect_response=False)
        self.client.get("/compte/totp/", secure=True)
        profile = Profile.objects.get(user__username="dan")
        response = self.client.post("/compte/totp/", {"code": pyotp.TOTP(profile.totp_secret).now()}, secure=True)
        codes = response.context["codes"]
        self.assertEqual(len(codes), 10)
        self.assertEqual(self.client.get("/", secure=True).status_code, 200)
        # Nouvelle connexion : le second facteur est exigé, un code déjà utilisé est refusé.
        self.client.post("/deconnexion/", secure=True)
        self.login("dan", "Nouveau-secret-2026!")
        self.assertRedirects(self.client.get("/", secure=True), "/connexion/code/", fetch_redirect_response=False)
        profile.refresh_from_db()
        replay = pyotp.TOTP(profile.totp_secret).at(timezone.now())
        if int(timezone.now().timestamp()) // 30 <= profile.totp_last_step:
            self.assertContains(self.client.post("/connexion/code/", {"code": replay}, secure=True), "Code invalide")
        self.client.post("/connexion/code/", {"code": codes[0]}, secure=True)
        self.assertEqual(self.client.get("/", secure=True).status_code, 200)
        self.client.post("/deconnexion/", secure=True)
        self.login("dan", "Nouveau-secret-2026!")
        self.assertContains(self.client.post("/connexion/code/", {"code": codes[0]}, secure=True), "Code invalide")

    def test_creation_de_compte_par_admin(self):
        admin = make_user("admin", role="admin")
        self.client.force_login(admin)
        response = self.client.post("/admin/comptes/nouveau/", {"username": "eve", "role": "reader",
                                                                "totp_required": "on"}, secure=True)
        password = response.context["password"]
        self.assertGreaterEqual(len(password), 24)
        eve = User.objects.get(username="eve")
        self.assertTrue(eve.check_password(password))
        self.assertTrue(eve.groups.filter(name=READER).exists())
        self.assertTrue(eve.profile.must_change_password and eve.profile.totp_required)
        self.assertTrue(AuditEvent.objects.filter(action="user_created", target="eve", actor=admin).exists())

    def test_dernier_admin_protege(self):
        admin = make_user("seul", role="admin")
        self.client.force_login(admin)
        response = self.client.post(f"/admin/comptes/{admin.pk}/", {"role": "reader", "is_active": "on"}, secure=True)
        self.assertContains(response, "dernier administrateur actif")
        self.assertTrue(User.objects.get(pk=admin.pk).is_superuser)

    def test_bootstrap_admin_et_journal_integre(self):
        from io import StringIO
        out = StringIO()
        call_command("bootstrap_admin", stdout=out)
        self.assertIn("MOT_DE_PASSE=", out.getvalue())
        call_command("bootstrap_admin", stdout=out)
        self.assertIn("EXISTANT", out.getvalue())
        self.assertEqual(User.objects.count(), 1)
        self.login("x", "y")
        self.assertEqual(verify(), [])

    def test_en_tetes_de_securite_et_sante(self):
        response = self.client.get("/connexion/", secure=True)
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(self.client.get("/sante/").content, b"ok")
        self.assertRedirects(self.client.get("/"), "https://testserver/", status_code=301, fetch_redirect_response=False)
