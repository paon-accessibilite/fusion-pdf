# Fusion PDF

Une petite application Windows pour assembler des documents PDF **entièrement en local**. Aucun document ni aucune donnée n'est envoyé sur Internet.

## Lancer l'application

La version recommandée pour le partage se trouve dans `dist/FusionPDF-Editeur-sans-installation.zip`. Elle est autonome : Python n'est pas nécessaire sur l'ordinateur de vos collègues. Il suffit d'extraire entièrement l'archive puis de lancer `FusionPDF-Editeur.exe` dans le dossier obtenu.

Cette distribution utilise un dossier d'application sans compression UPX. Contrairement au format « fichier unique », elle ne doit pas extraire ses bibliothèques dans un dossier temporaire à chaque lancement ; cela réduit les faux positifs de certains antivirus. Une signature numérique avec un certificat d'éditeur reste toutefois la seule manière d'afficher un éditeur vérifié dans Windows.

En cas de contrôle par le service informatique, l'empreinte SHA-256 de l'archive permet de vérifier que le fichier transmis n'a pas été modifié. Elle est communiquée avec chaque version distribuée.

Pour lancer la version de développement, double-cliquez sur `lancer.bat`. Au premier lancement seulement, le script installe le moteur PDF dans un environnement isolé. Les lancements suivants sont immédiats et fonctionnent hors ligne.

Vous pouvez aussi utiliser PowerShell :

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe app.py
```

## Utilisation

1. Glissez-déposez plusieurs PDF ou un dossier dans la fenêtre. Les boutons d'ajout restent disponibles.
2. Sélectionnez un document pour prévisualiser toutes ses pages.
3. Décochez les pages à exclure ; elles sont toutes sélectionnées par défaut.
4. Changez l'ordre des documents avec **Monter** et **Descendre**.
5. Cliquez sur **Fusionner les PDF** pour enregistrer directement le résultat sans quitter l'écran principal.
6. Utilisez **Fusionner et éditer** pour ouvrir une fusion temporaire dans l'éditeur sans choisir immédiatement un fichier de sortie.
7. Dans l'éditeur, glissez une page entre deux vignettes en suivant la barre verte d'insertion, ou utilisez les boutons. Vous pouvez également faire pivoter la page sélectionnée par incréments de 90°, supprimer des pages, ajuster le zoom, annuler ou rétablir vos changements, puis enregistrer une copie.

Le bouton **Modifier un PDF** permet aussi d'ouvrir directement un gros PDF existant dans cet éditeur, sans effectuer de fusion préalable.

Le bouton **?**, disponible sur les deux écrans, ouvre une notice intégrée en quatre pages. Chaque rubrique est cliquable pour afficher des explications détaillées. Le raccourci **Comparer les 2 modes** ouvre directement la comparaison complète entre la fusion immédiate et la fusion suivie d'une édition. Les flèches du clavier permettent également de parcourir les pages.

Les PDF protégés par mot de passe sont refusés afin d'éviter une fusion incomplète. Le fichier final est écrit de façon atomique : une erreur ne laisse pas derrière elle un PDF partiel.

## Reconstruire l'exécutable

Double-cliquez sur `construire_exe.bat`. Le dossier autonome et son archive prête à partager seront placés dans `dist`.
