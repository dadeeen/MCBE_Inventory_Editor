# Minecraft Bedrock Inventory Editor

[🇬🇧 English](README.md) | **🇩🇪 Deutsch**

[![CI](https://github.com/dadeeen/MCBE_Inventory_Editor/actions/workflows/ci.yml/badge.svg)](https://github.com/dadeeen/MCBE_Inventory_Editor/actions/workflows/ci.yml)
[![Lizenz: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12–3.14](https://img.shields.io/badge/Python-3.12%E2%80%933.14-blue.svg)](#lokaler-windows-start)

Ein lokaler Webeditor für ausgewählte Minecraft-Bedrock-Spielerdaten: Inventar, Endertruhe, Effekte, Fähigkeiten, Spielerwerte und experimentelle Mounts.

Die Oberfläche gibt es auf Deutsch und Englisch; die Sprache lässt sich in der Kopfzeile wechseln.

Dies ist ein inoffizielles Community-Projekt. Es ist weder mit Mojang Studios oder Microsoft verbunden noch von ihnen unterstützt oder autorisiert.

> **Vor jeder Bearbeitung:** Beende Minecraft oder den Bedrock-Server und erstelle eine vollständige, unabhängige Kopie der Welt. Behalte diese Kopie, bis die bearbeitete Welt in Minecraft geprüft wurde. App-Backups sind nur eine zusätzliche Schutzschicht.

Der Editor ist für die lokale Nutzung und vertrauenswürdige Heimnetze gedacht. Stelle ihn nicht direkt ins öffentliche Internet.

Studio-Layout mit Beispieldaten, englischer Oberfläche und integrierten Ersatzsymbolen:

[![Weltauswahl und Sicherheitsstatus](docs/assets/editor-overview.png)](docs/assets/editor-overview.png)

[![Beispielinventar](docs/assets/editor-inventory.png)](docs/assets/editor-inventory.png)

## Download → Backup → Start

Wähle, wie du den Editor starten möchtest:

| Variante | Einstieg | Voraussetzungen |
| --- | --- | --- |
| [Portable Windows-App](#portable-windows-app) | `_windows_x64.zip` → `MCBEInventoryEditor.exe` | Windows x64 und WebView2; Python ist enthalten |
| [Browser unter Windows](#lokaler-windows-start) | `_runtime.zip` → `setup.bat`, danach `start.bat` | Python 3.12–3.14 |
| [Docker / LAN](#docker-und-vertrauenswürdiges-lan) | Veröffentlichtes GHCR-Image und Compose | Docker mit Zugriff auf die beendeten Welten |

Alle drei Varianten verwenden denselben Editor. Die Release-ZIPs findest du unter [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).

Folge beim ersten Start dem Einrichtungsdialog. Lade **Item-DB** und **Vanilla-Icons** und warte auf die Abschlussmeldung. Du kannst das später unter **Werkzeuge** nachholen; bis dahin verwendet der Editor den mitgelieferten Item-Stand und Ersatzsymbole.

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
| Sicherheit | Backups vor dem Speichern, geprüfte Wiederherstellungen und Schutz vor gleichzeitigen Änderungen |
| Spielertransfer | Migration lokal ↔ Multiplayer und vollständiger `.mcbe-player.zip`-Import/-Export |
| Icons | Gemeinsame Vanilla-Icons, aktive Welt-Packs, `.mcpack`, `.zip` und eigene Icon-Ordner |
| Mounts | Experimentelle Erzeugung von Pferden, Eseln, Maultieren, Skelettpferden und Kamelen |
| Diagnose | Weltstatus, Runtime-Prüfungen, Berichte und privater Spieler-Rohdatenexport |

## Portable Windows-App

Entpacke das **gesamte** Release-Archiv mit der Endung `_windows_x64.zip` in einen beschreibbaren Ordner und starte `MCBEInventoryEditor.exe` per Doppelklick. Die EXE und der mitgelieferte Ordner `_internal` gehören zusammen. Eine separate Python-Installation ist nicht erforderlich.

Voraussetzung ist **Microsoft Edge WebView2 Runtime**. Falls sie fehlt, installiere die [offizielle Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).

Einstellungen, Icons und Backups liegen im Ordner `data` neben der EXE. Beim Schließen erinnert der Editor an ungespeicherte Änderungen und wartet auf laufende Schreibvorgänge.

**Programmupdate:** Beende den Editor, entpacke das vollständige neue Archiv in einen neuen Ordner und kopiere deinen bisherigen `data`-Ordner hinein. Starte dort `MCBEInventoryEditor.exe`.

Startfehler findest du in `data/desktop.log`. Bei unterbrochenen Wiederherstellungen hilft die [Recovery-Anleitung](SECURITY.de.md#unterbrochene-wiederherstellungen).

## Lokaler Windows-Start

1. Öffne [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).
2. Lade die Datei mit der Endung `_runtime.zip` herunter. Die automatisch erzeugten **Source code**-Archive sind keine startfertigen Pakete.
3. **Optional:** Lade die zugehörige `.sha256`-Datei herunter und vergleiche die Prüfsumme mit dem Ergebnis von `Get-FileHash <runtime.zip> -Algorithm SHA256` in PowerShell.
4. Beende Minecraft oder den Server und kopiere den vollständigen Weltordner an einen unabhängigen Ort.
5. Installiere bei Bedarf [Python für Windows](https://www.python.org/downloads/windows/) in Version **3.12–3.14**. Aktiviere den Python Launcher oder **Add Python to PATH**.
6. Entpacke das Runtime-ZIP, führe einmal `setup.bat` aus und starte danach mit `start.bat`. Der Editor öffnet sich automatisch im Browser. Falls nicht, öffne `http://127.0.0.1:5000` selbst.

Lass das von `start.bat` geöffnete Kommandozeilenfenster während der Nutzung offen. Ein geschlossener Browser-Tab beendet den Editor nicht. Speichere deine Änderungen und beende ihn anschließend mit **Strg+C** im Kommandozeilenfenster.

Im Quellcode-Checkout gelten dieselben Startbefehle. Einstellungen, Backups und heruntergeladene Icons liegen unter `data/`.

**Programmupdate:** Beende den Editor, entpacke die neue Version in einen neuen Ordner und kopiere deinen bisherigen `data`-Ordner hinein. Führe dort erneut `setup.bat` aus und starte mit `start.bat`.

## Docker und vertrauenswürdiges LAN

Für einen einfachen Einstieg verwendest du `latest`, um das aktuelle stabile Image zu laden:

```bash
docker pull ghcr.io/dadeeen/mcbe-inventory-editor:latest
```

`latest` folgt den stabilen Releases. Für eine feste Version ersetze `latest` durch die Versionsnummer auf der [Releases-Seite](https://github.com/dadeeen/MCBE_Inventory_Editor/releases), ohne das führende `v`.

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

Öffne anschließend `http://<Docker-Host>:8088` im Browser.

Für ein Update schließe deine Bearbeitungen ab und führe dieselben Befehle erneut aus; das Datenvolume bleibt erhalten. In einer Stack-Verwaltung lädst du das Image neu und stellst den Stack erneut bereit. `latest` aktualisiert laufende Container nicht automatisch.

Das ausführlich kommentierte [Compose-Beispiel auf GitHub](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docker-compose.example.yml) ergänzt Log-Rotation und Container-Beschränkungen.

Lege beim ersten Öffnen ein Passwort fest oder bestätige ausdrücklich den passwortlosen Betrieb in einem vertrauenswürdigen Netz. Schütze den Port mit Firewallregeln und richte weder öffentlichen Ingress noch öffentliche Tunnel ein.

Wichtiges Docker-Verhalten:

- Binde den gemeinsamen übergeordneten Weltordner unter `/worlds` ein, damit vollständige Wiederherstellungen möglich sind. Dauerhafte App-Daten und Backups liegen unter `/data`; halte dieses Volume persistent.
- `MCBE_REQUIRE_SERVER_OFFLINE=true` ist Standard. Ein erreichbarer konfigurierter Bedrock-Server blockiert Schreibvorgänge; ein unbekannter Status verlangt eine Bestätigung. Bei NetherNet muss der Editor auch den TCP-Port des Servers erreichen können.
- Für schreibgeschützten Zugriff verwende `MCBE_READ_ONLY=true` und zusätzlich `/worlds:ro`, siehe [Viewer-Beispiel](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docker-compose.viewer.example.yml). Docker `read_only: true` allein schützt eingebundene Welten nicht.
- Der Container läuft ohne Root-Rechte als UID/GID `10001`. Richte die nötigen [Schreibrechte für Docker-Welten](#schreibrechte-für-docker-welten) vor dem ersten Speichern ein.

### Schreibrechte für Docker-Welten

Die folgende Anleitung erklärt die Zugriffsrechte. Für vollständige Wiederherstellungen muss der Editor auch Eigentümer, Gruppen und Dateirechte übernehmen können; ACL- oder Gruppenschreibrechte allein garantieren das nicht. Verwende für vollständige Restore-Unterstützung dieselbe unprivilegierte UID/GID für Editor und Server wie unten beschrieben.

<details>
<summary>Docker-Dateirechte einrichten und Fehler prüfen</summary>

Ein `:rw`-Mount allein gewährt noch keine Schreibrechte. Wenn beispielsweise

```text
IO error: /worlds/MeineWelt/db/LOCK: Permission denied
```

erscheint, darf UID `10001` das Datenbankverzeichnis nicht beschreiben oder dort `LOCK` anlegen.

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

Die Default-ACL auf den Verzeichnissen sorgt dafür, dass neu angelegte Dateien und Unterordner den Editorzugriff erben.

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

Vor dem Start müssen `/srv/bedrock/worlds` und `/srv/mcbe-editor-data` für diese Identität schreibbar sein. Verwende hier niemals UID `0`.

Jeder Prozess in der gemeinsamen Gruppe beziehungsweise mit der gemeinsamen UID kann die Welten verändern. Verwende dafür eine eigene Gruppe oder nicht privilegierte Dienst-UID und keine breit verwendete Systemgruppe.

Nicht unterstützte Abkürzungen:

- kein `chmod -R 777` auf Welt- oder Datenverzeichnisse;
- kein `privileged: true` und kein Betrieb des Editors als Root zur Umgehung von Dateirechten;
- die LevelDB-Datei `db/LOCK` weder löschen noch Sperrprüfungen deaktivieren, um einen laufenden Server zu übergehen.

</details>

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

Die **Migration lokal ↔ Multiplayer** überträgt ausgewählte Spielerdaten und bewahrt die Identität des Zielspielers. Der Multiplayer-Zielspieler muss der Welt bereits einmal beigetreten sein. Der Quellspieler bleibt erhalten; Haustierbesitz wird nicht übertragen.

Ein `.mcbe-player.zip`-Import ersetzt den vollständigen Spielerdatensatz durch den exportierten Stand. Prüfe den Zielspieler anschließend in Minecraft.

Spielerexporte enthalten nicht anonymisierte Daten. Behandle sie als privat und hänge sie weder an öffentliche Issues noch an Commits.

## Experimentelle Mounts

In der Mount-Ansicht kannst du Reittiere nahe dem Spieler in der Oberwelt vormerken. Die Platzierungsprüfung zeigt:

- **Grün:** Platzierung zulässig.
- **Gelb:** Platzierung unsicher; Bestätigung erforderlich.
- **Rot:** Platzierung blockiert.

Erst beim Speichern werden Spieleränderungen und vorgemerkte Reittiere gemeinsam in die Welt geschrieben. Die Funktion ist experimentell; teste sie zuerst auf entbehrlichen Weltkopien.

## Datensicherheit und Datenschutz

- Bearbeiten funktioniert offline. Updates von **Item-DB** und **Vanilla-Icons** sowie die optionale Netzwerkprüfung benötigen Internetzugriff über HTTPS.
- Vor dem Speichern prüft der Editor Serverstatus, Dateisperren und zwischenzeitliche Änderungen. Vor jeder tatsächlichen Änderung erstellt er ein vollständiges Welt-Backup.
- Bei einer unterbrochenen Wiederherstellung oder ungewissem Ausgang behalte Backup und Wiederherstellungsdateien und folge vor weiteren Bearbeitungen der [Recovery-Anleitung](SECURITY.de.md#unterbrochene-wiederherstellungen).
- Weltordner müssen reguläre Dateien und Verzeichnisse enthalten. Symlinks, Windows-Junctions und andere Reparse-Points werden nicht unterstützt.
- Backups und Wiederherstellungen sind standardmäßig auf **1 GiB unkomprimiert** und **50.000 Einträge** pro Archiv begrenzt. Prüfe das Größenlimit unter **Werkzeuge → Backup-Manager** und halte genügend freien Speicher für Backup- und Restore-Kopien bereit.
- Welten, Backups, Exporte und Diagnosedaten können persönliche Angaben enthalten. Halte sie privat.

Die [Sicherheitsrichtlinie](SECURITY.de.md) beschreibt Betrieb, Wiederherstellung und Sicherheitsmeldungen. Der [Speichervertrag](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/save_contract.md#backups-and-restore) erläutert Backup-Limits und Prüfungen im Detail.

## Kompatibilität und Grenzen

- Die Serverprüfung ersetzt das Beenden von Minecraft oder des Bedrock-Servers nicht.
- Nicht alle Bedrock-Versionen, Add-ons und Weltformate sind abgedeckt. Prüfe Änderungen in Minecraft.
- Bei erkannten Datenbankfehlern oder fehlenden Dateien blockiert der Editor Schreibvorgänge. Er repariert beschädigte Datenbanken nicht.

## Entwicklung und Lizenz

Fehlerberichte und Beiträge sind willkommen. Verwende synthetische Beispieldaten und bereinigte Logs ohne persönliche Angaben oder Zugangsdaten.

Hinweise für Mitwirkende stehen in der [Entwicklerdokumentation](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md). Die [Bedrock-Engine-Prüfungen](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/engine-checks.md) beschreiben geprüfte Versionen, Testumfang und Grenzen.

Der eigene Projektcode steht unter der [MIT-Lizenz](LICENSE). Für Abhängigkeiten gelten deren jeweilige Lizenzen.

Minecraft-Inhalte gehören Mojang Studios/Microsoft und unterliegen deren Bedingungen. Die mitgelieferte Item-Datenbank basiert auf `Mojang/bedrock-samples` und Microsoft Learn; Vanilla-Icons werden nur auf Anforderung heruntergeladen.

Wichtige vorgelagerte Projekte sind das [Amulet Team](https://github.com/Amulet-Team), Flask und das Pallets-Team sowie das [Minecraft Wiki](https://minecraft.wiki/) als Referenz für manuell geprüfte Spielmechaniken.
