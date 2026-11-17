# Régressions à surveiller

| Zone | Comportement à préserver | Contrôle |
|---|---|---|
| Historique | Une recherche avec 50 résultats donne 20, 20 et 10 fiches. Le retour depuis une fiche conserve la page et les critères. | Test `test_historique_filtre_pagine_et_retour` dans `registre/tests.py`. |
| Recherche | Une référence, un équipement ou un service retrouve la fiche. Plusieurs services correspondants ne créent aucun doublon. | Test `test_recherche_reference_equipement_et_services_sans_doublons`. |
| Conservation | Les écrans d’administration interdisent la suppression des comptes et référentiels. La désactivation préserve le journal, et le personnel délégué ne peut pas modifier les comptes ou groupes. | Test `test_administration_preserve_les_references_et_les_auteurs`. |
| Comparaison | Le diff conserve le contexte et numérote correctement les lignes après un ajout ou une suppression. | Test `test_diff_conserve_les_lignes_et_leurs_numeros`. Vérifier la fiche VPN de démo à 1 672 × 941 px avec la référence Clair-obscur. |
| Capture | Deux images collées donnent deux miniatures et le retrait d’une miniature écarte le fichier. Les images enregistrées exigent une connexion. | Rejouer le collage et le retrait dans Edge. Test `test_captures_restent_privees_et_tracables` pour le stockage et l’accès. |
| Carte | Les branches représentent les services de la fiche. Le clavier permet d’ouvrir puis fermer la vue agrandie et de retrouver le bouton d’origine. | Ouvrir les exemples avec zéro, un et plusieurs services, puis rejouer sur mobile et au clavier. |
