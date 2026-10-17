# Minecraft Bedrock Inventory Editor

[🇬🇧 English](README.md) | **🇩🇪 Deutsch**

[![CI](https://github.com/dadeeen/MCBE_Inventory_Editor/actions/workflows/ci.yml/badge.svg)](https://github.com/dadeeen/MCBE_Inventory_Editor/actions/workflows/ci.yml)
[![Lizenz: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12–3.14](https://img.shields.io/badge/Python-3.12%E2%80%933.14-blue.svg)](#lokaler-windows-start)

Ein lokaler Webeditor für ausgewählte Minecraft-Bedrock-Spielerdaten: Inventar, Endertruhe, Effekte, Fähigkeiten, Spielerwerte und experimentelle Mounts.

Die Oberfläche gibt es auf Deutsch und Englisch. Ein Umschalter in der Kopfzeile wechselt jederzeit; Browser mit deutscher Spracheinstellung bekommen automatisch die deutsche Oberfläche.

Dies ist ein inoffizielles Community-Projekt. Es ist weder mit Mojang Studios oder Microsoft verbunden noch von ihnen unterstützt oder autorisiert.

> **Vor jeder Bearbeitung:** Beende Minecraft oder den Bedrock-Server und erstelle eine vollständige, unabhängige Kopie der Welt. Behalte diese Kopie, bis die bearbeitete Welt in Minecraft geprüft wurde. App-Backups sind nur eine zusätzliche Schutzschicht.

Der Editor ist für die lokale Nutzung und vertrauenswürdige Heimnetze gedacht. Stelle ihn nicht direkt ins öffentliche Internet.

Studio-Layout mit Beispieldaten, englischer Oberfläche und integrierten Ersatzsymbolen:

[![Weltauswahl und Sicherheitsstatus](docs/assets/editor-overview.png)](docs/assets/editor-overview.png)

[![Beispielinventar](docs/assets/editor-inventory.png)](docs/assets/editor-inventory.png)

### Besondere Items

Rechtsklick auf ein Item → **Inhalte bearbeiten**, oder die sichtbare Aktion im Slot-Editor verwenden. Shulkerkisten haben einen Editor mit 27 Slots; Bundles zeigen ihren Füllstand und unterstützen verschachtelte Bundles. Enthaltene Items verwenden dieselben Item- und Verzauberungsregeln wie das Hauptinventar.

Eigene Editoren stehen für Buchseiten, Titel und Autoren signierter Bücher, Feuerwerksraketen und -sterne sowie geordnete Bannermuster mit texturierter Vanilla-Vorschau bereit, einschließlich komplexer Motive, Farbstofffarben und transparenter Verläufe. Die Vorschau verwendet lokal gespeicherte Minecraft-Texturen; **Bannermuster laden** ergänzt fehlende Texturen über das Vanilla-Icon-Update und hält sie offline verfügbar. Jeder Dialog führt einen lokalen Entwurf: **Übernehmen** erzeugt einen Rückgängig-Schritt; **Abbrechen** verwirft ihn. Erst das Speichern des Spielers schreibt die Änderungen in die Welt. Per Tastatur öffnet **Umschalt+F10** das Item-Menü; die Pfeiltasten wählen eine Aktion aus.

Unbekannte Zusatzdaten bleiben erhalten. Nicht unterstützte Spezialdatenformate sind schreibgeschützt. Die unterstützten Formate, Grenzen und Quellen stehen im [Speichervertrag auf GitHub](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/save_contract.md#special-item-edits).

## Download → Backup → Start

Wähle die passende Ausgabe:

| Ausgabe | Einstieg | Voraussetzungen |
| --- | --- | --- |
| [Portable Windows-App](#portable-windows-app) | `_windows_x64.zip` → `MCBEInventoryEditor.exe` | Windows x64 und WebView2; Python ist enthalten |
| [Browser unter Windows](#lokaler-windows-start) | `_runtime.zip` → `setup.bat`, danach `start.bat` | Python 3.12–3.14 |
| [Docker / LAN](#docker-und-vertrauenswürdiges-lan) | Veröffentlichtes GHCR-Image und Compose | Docker mit Zugriff auf die beendeten Welten |

Alle Ausgaben verwenden denselben Editor. ZIPs und passende `.sha256`-Dateien findest du unter [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).

### Browser-Ausgabe unter Windows

1. Öffne [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).
2. Lade die Datei mit der Endung `_runtime.zip` und die zugehörige `.sha256`-Datei herunter. Die automatisch erzeugten **Source code**-Archive sind Repository-Schnappschüsse und keine startfertigen Pakete.
3. Prüfe bei Bedarf die Prüfsumme:
   - Windows: `Get-FileHash <runtime.zip> -Algorithm SHA256`
   - Linux: `sha256sum <runtime.zip>`
4. Beende Minecraft oder den Server und kopiere den vollständigen Weltordner an einen unabhängigen Ort.
5. Installiere bei Bedarf [Python für Windows](https://www.python.org/downloads/windows/). Für Windows x64 empfehlen wir **Python 3.14**; 3.12 und 3.13 werden ebenfalls unterstützt. Aktiviere den Python Launcher oder **Add Python to PATH**. Runtime-ZIP und Quellcode-Checkout verwenden dieselbe Installation ohne Compiler. Python 3.15 ist noch nicht freigegeben.
6. Entpacke das Runtime-ZIP, führe einmal `setup.bat` aus und starte den Editor danach mit `start.bat`.
7. Folge beim ersten Start dem Einrichtungsdialog und lade **Item-DB** und **Vanilla-Icons**. Du kannst den Schritt aufschieben und später über den Einrichtungshinweis oder unter **Werkzeuge** nachholen. Der Editor bringt nur einen mitgelieferten Item-Stand und keine Icons mit — ohne diesen Schritt fehlen Items neuerer Minecraft-Versionen und jeder Slot zeigt ein Ersatzsymbol.
8. Lass das von `start.bat` geöffnete Kommandozeilenfenster während der Nutzung offen. Schließt du es, endet der lokale Editor-Prozess; ein noch offener Browser-Tab verliert dann die Verbindung und kann keine Daten mehr laden oder speichern.

Ein Item- oder Icon-Update prüft und verarbeitet auch die heruntergeladenen Dateien. Warte auf die Abschlussmeldung, bevor du den Editor schließt.

## Warum es dieses Projekt gibt

Der Editor ist für einen privaten Bedrock-Server entstanden. Kleine Korrekturen an Inventar oder Spielerwerten bedeuteten jedes Mal, die Weltdateien an einen Windows-Rechner zu kopieren — für eine Routinekorrektur unverhältnismäßig viel Aufwand.

Ziel war, solche Anpassungen von jedem Gerät im selben Netz aus vornehmen zu können. Die Docker-Instanz läuft neben dem Server, die Weboberfläche funktioniert von Laptop, Tablet oder Handy — ohne Windows-Rechner und ohne lokale Kopie der Welt.

Diese Herkunft erklärt den Zuschnitt: ein geprüfter Satz von Spielerfeldern, bearbeitet bei beendeter Welt und mit Backup, statt eines allgemeinen Welteditors.

## Unterstützte Bereiche

| Bereich | Umfang |
|---|---|
| Inventar | Hotbar, Rucksack, Rüstung, Schildhand, Verschieben, Kopieren und Sammelaktionen |
| Endertruhe | Anzeigen und Bearbeiten einschließlich Transfers zwischen sichtbaren Bereichen |
| Spielerwerte | Gesundheit, Spielmodus, XP, Hunger, Sättigung, Position, Effekte sowie Lauf- und Fluggeschwindigkeit |
| Sicherheit | Backups vor Schreibvorgängen, Restore-Prüfungen, Revisionen, Schreibsperren und Welt-Locks |
| Spielertransfer | Versionierte Migration lokal ↔ Multiplayer sowie vollständiger `.mcbe-player.zip`-Import/-Export |
| Icons | Gemeinsame Vanilla-Icons, aktive Welt-Packs, `.mcpack`, `.zip` und eigene Icon-Ordner |
| Mounts | Experimentelle Erzeugung von Pferden, Eseln, Maultieren, Skelettpferden und Kamelen |
| Diagnose | Weltstatus, Runtime-Prüfungen, Berichte und privater Spieler-Rohdatenexport |

Die App ist kein öffentlicher Hostingdienst, kein Server-Administrationspanel und kein uneingeschränkter Roh-NBT-Editor.

Icons berücksichtigen aktive Welt-Packs, deren Versionen und Priorität. Ausdrücklich im Editor hinzugefügte Quellen gelten global; Vanilla-Icons teilen einen lokalen Cache. Fehlende Packs oder nicht unterstützte Texturen verwenden Standard-Icons oder Ersatzsymbole. Eigene Blockmodelle, dynamische Darstellung und globale Pack-Einstellungen des Minecraft-Clients sind nicht abgedeckt. Die [Icon-Auflösung](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/icon-resolution.md) beschreibt unterstützte Formate und Cache-Verhalten.

## Drei Layouts

Wähle zwischen **Klassisch**, **Studio** und **Fokus**, unabhängig vom hellen oder dunklen Farbtheme. Beim Layoutwechsel bleiben laufende Bearbeitungen erhalten. Das Theme **System** folgt der hellen oder dunklen Einstellung des Betriebssystems, auch bei Änderungen während der Editor geöffnet ist.

## Portable Windows-App

Entpacke das **gesamte** Release-Archiv mit der Endung `_windows_x64.zip` in einen beschreibbaren Ordner und starte `MCBEInventoryEditor.exe` per Doppelklick. Python, Node.js, BAT-Dateien und Administratorrechte sind dafür nicht erforderlich. Die EXE und der mitgelieferte Ordner `_internal` gehören zusammen.

Das eigene Fenster verwendet dieselbe Oberfläche und dieselben Speicherdienste wie Browser und Docker. Es benötigt **Microsoft Edge WebView2 Runtime**, die auf Windows 11 normalerweise vorhanden ist. Fehlt sie, installiere die [offizielle Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). Die EXE installiert keine Systemkomponenten selbst. Zielplattform ist Windows x64; der Build enthält CPython 3.12.

Einstellungen, Icons, Backups und Fensterprofil liegen im beim Start angelegten Ordner `data` neben der EXE. Der lokale Dienst bindet ausschließlich an `127.0.0.1`, standardmäßig Port `5001`; der Browserstart verwendet weiterhin Port `5000`. Pro Datenordner läuft ein Desktop-Fenster. Beim Schließen werden ungespeicherte Änderungen abgefragt und laufende Schreibvorgänge abgeschlossen. Startfehler stehen in `data/desktop.log`.

Das Fenster bleibt beim lokalen Editor; angeklickte externe HTTP(S)-Links öffnen sich im Standardbrowser. Ist der Bearbeitungsstand nicht prüfbar, erfordert das Schließen eine Bestätigung. Für unterbrochene Wiederherstellungen steht `--recover` ohne Python-Installation bereit; siehe [Recovery-Anleitung](SECURITY.de.md#unterbrochene-wiederherstellungen).

Für ein Update den Editor schließen. Das Installationsverzeichnis kann bleiben: Ersetze die EXE, den **gesamten** Ordner `_internal` und die übrigen Paketdateien einschließlich `RELEASE_MANIFEST.json` durch die zusammengehörige neue Version; behalte dabei `data`. Nur die EXE auszutauschen reicht nicht; entferne den alten Ordner `_internal`, bevor du den neuen hineinkopierst. Alternativ kannst du das Archiv in einen neuen Ordner entpacken und `data` hineinkopieren, damit die alte Installation erhalten bleibt, bis die neue geprüft ist.

Der erste Item-DB-/Icon-Download und die Regeln zum Beenden und Sichern der Welt gelten auch hier. Browserinstallation und Docker benötigen keine Desktop-Abhängigkeiten. Der [Desktop-Build](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/desktop.md) beschreibt Architektur, Prüfungen und Pflege.

## Lokaler Windows-Start

Dieses Setup gilt für die Browser-Ausgabe. Es unterstützt **Python 3.12–3.14** und verwendet im Quellcode-Checkout und im entpackten Runtime-ZIP dieselben Befehle:

```bat
setup.bat
start.bat
```

`setup.bat` behält eine unterstützte vorhandene `.venv` bei oder erstellt sie mit der neuesten installierten unterstützten Python-Version. Es installiert hashgeprüfte Wheels innerhalb dieser Umgebung, ohne Compiler oder globale Python-Pakete. Der Editor öffnet sich unter `http://127.0.0.1:5000`; App-Daten liegen unter `data/`.

Lass die Konsole während der Bearbeitung offen. Das Schließen eines Browser-Tabs lässt den lokalen Dienst weiterlaufen; speichere deine Änderungen und beende ihn danach mit **Strg+C** in der Konsole. Die portable EXE wird über ihr eigenes Fenster geschlossen.

Administratorrechte sollten normalerweise nicht erforderlich sein. Falls eine sicher beendete Welt wegen Windows-Dateirechten nicht gespeichert werden kann, kann der Start als Administrator als Diagnosetest dienen. Eine laufende Welt wird dadurch nicht sicher bearbeitbar.

## Docker und vertrauenswürdiges LAN

Für einen einfachen Einstieg verwendest du `latest`, um das aktuelle stabile Image zu laden:

```bash
docker pull ghcr.io/dadeeen/mcbe-inventory-editor:latest
```

Stabile Releases aktualisieren `latest`, Vorabversionen nicht. Wenn du eine bestimmte Version beibehalten möchtest, ersetze `latest` durch die Version auf der [Releases-Seite](https://github.com/dadeeen/MCBE_Inventory_Editor/releases), ohne das führende `v`. So entscheidest du ausdrücklich über jeden Versionswechsel.

Speichere dieses Beispiel als `compose.yaml` oder verwende es als Stack. Ersetze `/PFAD/ZU/BEDROCK/WORLDS` durch den vorhandenen Hostordner mit deinen Welten. Trage bei `MCBE_SERVER_HOST` die aus dem Container erreichbare Adresse deines Bedrock-Servers ein und passe bei Bedarf dessen Port an:

```yaml
services:
  mcbe-editor:
    image: ghcr.io/dadeeen/mcbe-inventory-editor:latest
    restart: unless-stopped
    ports:
      - "8088:8080"
    environment:
      MCBE_SERVER_HOST: "192.168.1.100"
      MCBE_SERVER_PORT: "19132"
    volumes:
      - /PFAD/ZU/BEDROCK/WORLDS:/worlds:rw
      - mcbe-editor-data:/data:rw

volumes:
  mcbe-editor-data:
```

Lade im Verzeichnis mit der `compose.yaml` das Image und starte den Editor im Hintergrund:

```bash
docker compose pull
docker compose up -d
```

Für ein Update verwendest du dieselben Befehle, nachdem du deine Bearbeitungen abgeschlossen hast. `latest` aktualisiert einen laufenden Container nicht automatisch; durch erneutes Laden und Erstellen wird das heruntergeladene Image verwendet, während das benannte Datenvolume erhalten bleibt. In einer Stack-Verwaltung lädst du das Image neu und stellst den Stack erneut bereit.

Das [Compose-Beispiel auf GitHub](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docker-compose.example.yml) verwendet dasselbe veröffentlichte Image und ergänzt Kommentare, Log-Rotation und Container-Beschränkungen. Kopiere es nach `compose.yaml`, passe Weltpfad und Serveradresse an und verwende die obigen Befehle.

Lege beim ersten Öffnen ein Passwort fest oder bestätige ausdrücklich den passwortlosen Betrieb in einem vertrauenswürdigen Netz. Schütze den Port mit Firewallregeln und richte weder öffentlichen Ingress noch öffentliche Tunnel ein.

Wichtiges Docker-Verhalten:

- Welten werden unter `/worlds` gelesen; dauerhafte App-Daten und Backups liegen unter `/data`.
- `MCBE_REQUIRE_SERVER_OFFLINE=true` ist Standard. Ein erreichbarer konfigurierter Bedrock-Server blockiert Schreibvorgänge; ein unbekannter Status verlangt eine Bestätigung. Die Prüfung erkennt beide Server-Transporte auf `MCBE_SERVER_PORT`: RakNet am UDP-Ping und NetherNet (`transport=nethernet`) an einer HTTP-Anfrage an `/v1/join` über TCP. Bei NetherNet muss der Editor diesen TCP-Port erreichen können, sonst bleibt der Status unbekannt.
- `MCBE_READ_ONLY=true` schaltet die App in den schreibgeschützten Viewer-Modus. Binde für eine echte Viewer-Instanz zusätzlich `/worlds:ro` ein; Docker `read_only: true` schützt eingebundene Welten nicht.
- Binde bei schreibfähigen Instanzen den gemeinsamen übergeordneten Weltordner unter `/worlds` ein, nicht nur eine einzelne Welt. Restore-Staging und Rollback benötigen Zugriff auf Geschwisterpfade.
- Der Container läuft ohne Root-Rechte als UID/GID `10001`; der Hostordner muss die erforderlichen Rechte gewähren. Ein `:rw`-Mount allein genügt nicht — richte das **vor** dem ersten Speichern ein, siehe [Schreibrechte für Docker-Welten](#schreibrechte-für-docker-welten).
- Der Einrichtungshinweis beim ersten Start gilt auch hier: **Item-DB** und **Vanilla-Icons** liegen unter `/data` — halte dieses Volume persistent und erlaube dem Container ausgehendes HTTPS.
- Ein erfolgreiches vollständiges Item-DB-Update legt einen Verifikationsbeleg neben der Datenbank unter `/data` ab. Er ist an genau diese Datenbankdatei und ihre Quellmetadaten gebunden: Ein Browserwechsel erhält den geprüften Zustand, während das Löschen oder Ersetzen von `/data` bewusst ein neues vollständiges Item-DB-Update erfordert.

### Schreibrechte für Docker-Welten

Das Host-Dateisystem muss UID/GID `10001` vor dem ersten Speichern Zugriff gewähren. Klappe die Anleitung auf, wenn Berechtigungen angepasst werden müssen. Ein vollständiger Welt-Restore übernimmt zusätzlich die vorhandenen Eigentümer, Gruppen und Zugriffsrechte vor dem Ersetzen der Welt. ACL- oder Gruppenschreibrechte allein erlauben keine Übernahme eines anderen Eigentümers: Ist diese nicht möglich, bricht der Restore vor dem Ersetzen ab. Verwende für vollständige Restore-Unterstützung dieselbe unprivilegierte UID/GID für Editor und Server wie unten beschrieben.

<details>
<summary>Docker-Dateirechte einrichten und Fehler prüfen</summary>

Ein `:rw`-Mount allein gibt dem Prozess im Container noch keine Schreibrechte. Der Editor läuft absichtlich ohne Root-Rechte als UID/GID `10001`. Wenn beispielsweise

```text
IO error: /worlds/MeineWelt/db/LOCK: Permission denied
```

erscheint, darf UID `10001` das LevelDB-Verzeichnis nicht beschreiben oder dort die Datei `LOCK` nicht anlegen. Das kann auch dann der Fall sein, wenn `LOCK` noch gar nicht existiert.

Beende den Bedrock-Server vor allen folgenden Änderungen und ermittle zuerst den tatsächlich eingebundenen Hostpfad:

```bash
docker inspect mcbe-editor --format \
  '{{range .Mounts}}{{println .Source "->" .Destination "Mode:" .Mode}}{{end}}'
```

Ersetze `mcbe-editor` gegebenenfalls durch den eigenen Containernamen.

#### Empfohlen: gezielte ACL für UID 10001

Dieser Weg lässt Eigentümer und Gruppe der Serverdateien unverändert und gewährt nur dem Editor zusätzlich Zugriff. Installiere auf Debian/Ubuntu bei Bedarf zuerst das Paket `acl` (auf anderen Distributionen mit dem jeweiligen Paketmanager) und setze `WORLDS_ROOT` auf den Hostpfad, der nach `/worlds` eingebunden ist:

```bash
sudo apt-get install -y acl

WORLDS_ROOT=/var/lib/docker/volumes/MEIN_VOLUME/_data/worlds

sudo setfacl -R -m u:10001:rwX "$WORLDS_ROOT"
sudo find "$WORLDS_ROOT" -type d -exec setfacl -m d:u:10001:rwX {} +
```

Die Default-ACL auf den Verzeichnissen sorgt dafür, dass neu angelegte Dateien und Unterordner den Editorzugriff erben. Binde den gemeinsamen Weltordner und nicht nur eine einzelne Welt ein, damit Restore und Rollback ihre sicheren temporären Geschwisterpfade anlegen können.

Prüfe anschließend mit dem tatsächlichen Weltordner. `ls /worlds` gibt die echten Ordnernamen aus; setze `WORLD` auf einen davon, statt den Platzhalter stehen zu lassen:

```bash
docker exec mcbe-editor sh -lc '
id
ls /worlds
WORLD=/worlds/MeineWelt/db
if [ ! -d "$WORLD" ]; then
  echo "Pfad nicht gefunden: $WORLD"
elif [ -w "$WORLD" ]; then
  echo "Welt-Datenbank ist beschreibbar"
else
  echo "Welt-Datenbank ist NICHT beschreibbar"
fi
'
```

#### Kompatibilitätsmodus: gemeinsame Gruppe oder gemeinsame UID

Wenn ACLs auf dem Host-Dateisystem nicht zuverlässig verfügbar sind, können der Bedrock-Server und der Editor absichtlich eine dedizierte gemeinsame Gruppe verwenden. Beispiel mit GID `12000`:

```yaml
services:
  mcbe-editor:
    group_add:
      - "12000"
```

Auf dem Host müssen die Weltdateien dieser Gruppe gehören, gruppenbeschreibbar sein und neue Unterordner die Gruppe erben:

```bash
WORLDS_ROOT=/var/lib/docker/volumes/MEIN_VOLUME/_data/worlds

sudo chgrp -R 12000 "$WORLDS_ROOT"
sudo chmod -R g+rwX "$WORLDS_ROOT"
sudo find "$WORLDS_ROOT" -type d -exec chmod g+s {} +
```

Der Bedrock-Serverprozess benötigt dieselbe zusätzliche Gruppe. Beide Prozesse müssen neue Dateien gruppenbeschreibbar anlegen, üblicherweise mit `umask 0002`; ohne diese gemeinsame Umask ist der Gruppenmodus für später neu angelegte Dateien nicht zuverlässig.

Für maximale Kompatibilität können beide Container stattdessen bewusst unter derselben **nicht privilegierten** UID/GID laufen:

```yaml
services:
  mcbe-editor:
    user: "1234:1234"  # Beispiel: dieselbe UID/GID wie der Bedrock-Server
    volumes:
      - /srv/bedrock/worlds:/worlds:rw
      - /srv/mcbe-editor-data:/data:rw
```

Vor dem Start müssen `/srv/bedrock/worlds` und `/srv/mcbe-editor-data` für diese Identität schreibbar sein. Verwende hier niemals UID `0`. Diese gemeinsame Identität funktioniert auch bei restriktiver Umask zuverlässiger, reduziert die Isolation aber stärker: Editor und Server besitzen aus Sicht des Kernels dieselben Dateirechte.

Beide Kompatibilitätsvarianten reduzieren die Isolation. Jeder Prozess und Benutzer in der gemeinsamen Gruppe beziehungsweise mit der gemeinsamen UID kann die Welten verändern. Verwende dafür eine eigene Gruppe oder nicht privilegierte Dienst-UID und keine breit verwendete Systemgruppe.

Nicht unterstützte Abkürzungen:

- kein `chmod -R 777` auf Welt- oder Datenverzeichnisse;
- kein `privileged: true` und kein Betrieb des Editors als Root zur Umgehung von Dateirechten;
- die LevelDB-Datei `db/LOCK` weder löschen noch Sperrprüfungen deaktivieren, um einen laufenden Server zu übergehen.

Diese Maßnahmen beheben die Besitz- und Rechteursache nicht oder entfernen wichtige Schutzschichten für Isolation und Parallelzugriff.

</details>

Das [Viewer-Beispiel](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docker-compose.viewer.example.yml) richtet schreibgeschützten Zugriff ein. Lokale Build-Hilfen liegen unter `scripts/docker/` im Quellcode-Checkout oder Runtime-ZIP. Für einen eigenen Build führst du im Hauptverzeichnis des Checkouts oder Runtime-Pakets `docker build -t mcbe-inventory-editor:local .` aus und setzt in Compose `image: mcbe-inventory-editor:local`.

## Sicherer Arbeitsablauf

1. Beende Minecraft oder den Bedrock-Server.
2. Erstelle eine unabhängige Kopie der vollständigen Welt.
3. Wähle Welt und Spieler im Editor aus.
4. Nimm die Änderungen vor und prüfe sie.
5. Speichere. Vor einem tatsächlichen Schreibvorgang wird ein Backup erstellt.
6. Schließe den Editor, öffne die Welt in Minecraft und prüfe das Ergebnis.
7. Behalte die unabhängige Kopie bis zum Abschluss der Prüfung.

Der Editor beendet oder startet Minecraft beziehungsweise einen Bedrock-Server nicht selbst.

## Spielermigration und Import

Die **Migration lokal ↔ Multiplayer** überträgt eine explizite Positivliste von Spielzuständen und bewahrt die Identität sowie unbekannte Felder des Zielspielers. Dazu gehören geprüfte Vanilla-Attribute, der letzte Todesort, der Schlaf-/Phantomzustand und Rezeptfreischaltungen. Rezepte werden verlustfrei vereinigt: Fehlende Quellrezepte werden ergänzt, vorhandene Zielrezepte bleiben erhalten. Der Multiplayer-Zielspieler muss der Welt bereits einmal beigetreten sein. Der Quelldatensatz wird nicht gelöscht; Haustierbesitz wird nicht neu zugeordnet.

Ein vollständiger `.mcbe-player.zip`-Import ist etwas anderes: Er schreibt den exportierten Spielerdatensatz als Ganzes. Beide Vorgänge erstellen ein geprüftes Backup, validieren den Schreibvorgang und versuchen bei Fehlern ein Rollback. Prüfe den Zielspieler anschließend immer in Minecraft.

Spielerexporte enthalten rohe, nicht anonymisierte NBT-Daten. Behandle sie als privat und hänge sie weder an öffentliche Issues noch an Commits.

Für Rohdatenexporte per Kommandozeile siehe [private Spielerdiagnose](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md#private-player-diagnostics). Diese Werkzeuge benötigen die Browser-Runtime oder einen Quellcode-Checkout; die Desktop-EXE bietet keine allgemeine Python-CLI.

## Experimentelle Mounts

Die Mount-Ansicht kann Pferde, Esel, Maultiere, Skelettpferde und Kamele nahe dem Spieler in der Oberwelt vormerken. Die Platzierung wird anhand dekodierter Geländedaten geprüft:

- grüne Kandidaten werden akzeptiert;
- gelbe Kandidaten konnten nicht sicher bestätigt werden und benötigen eine ausdrückliche Bestätigung;
- rote Kandidaten werden serverseitig abgelehnt.

Das Vormerken schreibt noch nichts in die Welt. Der bestätigte Workspace-Speichervorgang erstellt ein Backup und schreibt Spieler- und Mount-Datensätze gemeinsam. Gelände, Dimensionen, Add-ons und künftige Bedrock-Versionen sind nicht vollständig abgedeckt; teste die Funktion zuerst auf entbehrlichen Weltkopien.

## Datensicherheit und Datenschutz

Der Editor lässt nicht unterstützte Bedrock- und Add-on-Daten unangetastet, statt sich wie ein vollständiger Roh-NBT-Editor zu verhalten. Unbekannte Formate können Annahmen dennoch ungültig machen. Kein Backup und keine Validierung können die semantische Korrektheit jeder Welt oder künftigen Minecraft-Version garantieren.

Praktische Schutzmaßnahmen und Grenzen:

- Bearbeiten funktioniert offline. Updates von **Item-DB** und **Vanilla-Icons** benötigen ausgehendes HTTPS; auch die optionale Netzwerkprüfung beim Start kontaktiert deren zugelassene Hosts.
- Schreibvorgänge prüfen geladene Spielerrevision, Welt-Lock und Serverstatus. Jeder tatsächliche Schreibvorgang benötigt ein geprüftes vollständiges Welt-Backup; ein unverändertes Speichern schreibt nichts und erstellt kein Backup.
- Restore prüft das Archiv und erstellt ein Pre-Restore-Backup. Bei einer unterbrochenen Wiederherstellung oder ungewissem Ausgang behältst du Backup und Wiederherstellungsdateien und befolgst vor weiteren Bearbeitungen die [Recovery-Anleitung](SECURITY.de.md#unterbrochene-wiederherstellungen).
- Weltordner müssen reguläre Dateien und Verzeichnisse enthalten. Symlinks, Windows-Junctions und andere Reparse-Points werden nicht unterstützt.
- Backups und Restore sind standardmäßig auf **1 GiB unkomprimiert** und höchstens **50.000 Einträge** pro Archiv begrenzt. Das Größenlimit lässt sich unter **Werkzeuge → Backup-Manager** ändern. Eine ausdrückliche Vorgabe über `MCBE_BACKUP_MAX_UNCOMPRESSED_MIB` hat Vorrang vor dem gespeicherten Wert. Halte ausreichend freien Speicher für Backup- und Restore-Kopien bereit.
- Welten, Backups, Exporte, Diagnosen und Audit-Logs können identifizierende Angaben enthalten. Halte sie privat und außerhalb von Repositorys und Release-Archiven. Lokale App-Daten liegen in `data/`; Docker verwendet `/data` einschließlich `/data/backups`.

Die [Sicherheitsrichtlinie](SECURITY.de.md) beschreibt Betrieb, Wiederherstellung und Sicherheitsmeldungen. Der [Speichervertrag](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/save_contract.md#backups-and-restore) erläutert Backup-Limits und Prüfungen im Detail.

## Kompatibilität und Grenzen

- Linux-Bedrock-Server können eine Welt ohne LevelDB-`LOCK` offenhalten; Dateisperren allein beweisen daher nicht, dass der Server beendet ist. Lass die Serverstatus-Prüfung konfiguriert und beende den tatsächlichen Server vor der Bearbeitung.
- Fehlende oder widersprüchliche Datenbankdateien und überschrittene [Leselimits](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/leveldb-writer.md) blockieren Schreibvorgänge. Der Editor repariert beschädigte Datenbanken nicht.
- Bedrock-Updates, Add-ons, undurchsichtige NBT-Daten und ungewöhnliche LevelDB-Strukturen können außerhalb dessen liegen, wofür der Editor ausgelegt ist.
- Die experimentelle Mount-Platzierung bildet nicht die vollständige Minecraft-Kollisionsphysik ab.
- Release-ZIPs besitzen eine SHA-256-Prüfsumme und ein internes Dateimanifest, aber keine unabhängige kryptografische Signatur.

## Entwicklung und Lizenz

Fehlerberichte und Beiträge sind willkommen. Verwende synthetische Daten und bereinigte Logs; hänge niemals echte Welten, Backups, Spielerexporte, Audit-Exporte, Spielernamen, private Pfade oder Zugangsdaten an.

Hinweise für Mitwirkende, Tests, Fixtures und Release-Hygiene stehen in [docs/development.md auf GitHub](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md). Interne Speicherinvarianten stehen in [docs/save_contract.md](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/save_contract.md).

Optionale [Bedrock-Engine-Prüfungen](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/engine-checks.md) dokumentieren geprüfte Versionen, Umfang und verbleibende Lücken. Ihre Entwicklerwerkzeuge, Mojangs Serverprogramme und erzeugte Testwelten sind von Runtime-Paketen ausgeschlossen.

Der eigene Projektcode steht unter der [MIT-Lizenz](LICENSE). Für die Laufzeitabhängigkeiten gelten deren jeweilige vorgelagerte Lizenzen. Amulet-LevelDB, Amulet-NBT und ihre Abhängigkeiten werden ausschließlich in der separat installierten Python-3.12-Referenztestumgebung verwendet und nicht mit der Runtime ausgeliefert; ihre vorgelagerten Lizenzbedingungen gelten für diese Testumgebung.

Minecraft-Inhalte fallen nicht unter die Lizenz dieses Projekts. Das Repository enthält einen aus `Mojang/bedrock-samples` und Microsoft Learn erzeugten Item-Datenstand; Vanilla-Icons werden nur auf Anforderung heruntergeladen und nicht mitgeliefert. Die Herkunft der lokal gepflegten Verzauberungs-Maximalstufen ist in [docs/development.md auf GitHub](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md#bundled-item-database-and-enchantment-max-levels) dokumentiert. Minecraft und seine Inhalte gehören Mojang Studios/Microsoft und unterliegen deren Bedingungen.

Wichtige vorgelagerte Projekte sind das [Amulet Team](https://github.com/Amulet-Team), Flask und das Pallets-Team sowie das [Minecraft Wiki](https://minecraft.wiki/) als Referenz für manuell geprüfte Spielmechaniken.
