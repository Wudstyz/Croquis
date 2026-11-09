# Composants tiers / Third-party components

Croquis embarque les composants suivants (chacun reste sous sa propre licence) :
Croquis bundles the following components (each remains under its own license):

| Composant / Component | Rôle / Role | Licence / License |
|---|---|---|
| [CPython](https://www.python.org/) 3.14 (via [python-build-standalone](https://github.com/astral-sh/python-build-standalone)) | Interpréteur Python embarqué / embedded interpreter | PSF License |
| [NumPy](https://numpy.org/) | Calcul sur les images / image arrays | BSD-3-Clause |
| [SciPy](https://scipy.org/) (`scipy.ndimage` uniquement / only) | Flous, distances, composantes connexes | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | Lecture et écriture des images, PDF | MIT-CMU (HPND) |
| [pywebview](https://pywebview.flowrl.com/) | Fenêtre native | BSD-3-Clause |
| [PyObjC](https://pyobjc.readthedocs.io/) | Liaison avec macOS (Cocoa, WebKit) | MIT |

Les textes complets des licences sont distribués avec chaque bibliothèque (dossiers `*.dist-info` dans l'app).
Full license texts ship with each library (`*.dist-info` folders inside the app).

## Marques / Trademarks

macOS, Apple Silicon et les autres marques citées appartiennent à leurs propriétaires respectifs ; ce projet n'est affilié à aucun d'eux.
macOS, Apple Silicon and other names mentioned belong to their respective owners; this project is not affiliated with any of them.

## Image d'exemple / Sample image

L'illustration « Exemple » est dessinée par le programme lui-même (`sample.py`) : aucune image tierce n'est embarquée.
The "Exemple" illustration is drawn by the program itself (`sample.py`); no third-party image is bundled.
