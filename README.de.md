# Minecraft Bedrock Inventory Editor

[🇬🇧 English](README.md) | **🇩🇪 Deutsch**

[![CI](https://github.com/dadeeen/MCBE_Inventory_Editor/actions/workflows/ci.yml/badge.svg)](https://github.com/dadeeen/MCBE_Inventory_Editor/actions/workflows/ci.yml)
[![Lizenz: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](#lokaler-windows-start)

Ein lokaler Webeditor für ausgewählte Minecraft-Bedrock-Spielerdaten: Inventar, Endertruhe, Effekte, Fähigkeiten, Spielerwerte und experimentelle Mounts.

Die Oberfläche gibt es auf Deutsch und Englisch. Ein Umschalter in der Kopfzeile wechselt jederzeit; Browser mit deutscher Spracheinstellung bekommen automatisch die deutsche Oberfläche.

Dies ist ein inoffizielles Community-Projekt. Es ist weder mit Mojang Studios oder Microsoft verbunden noch von ihnen unterstützt oder autorisiert.

> **Vor jeder Bearbeitung:** Beende Minecraft oder den Bedrock-Server und erstelle eine vollständige, unabhängige Kopie der Welt. Behalte diese Kopie, bis die bearbeitete Welt in Minecraft geprüft wurde. App-Backups sind nur eine zusätzliche Schutzschicht.

Der Editor ist für die lokale Nutzung und vertrauenswürdige Heimnetze gedacht. Stelle ihn nicht direkt ins öffentliche Internet.

## Download → Backup → Start

1. Öffne [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).
2. Lade die Datei mit der Endung `_runtime.zip` und die zugehörige `.sha256`-Datei herunter. Die automatisch erzeugten **Source code**-Archive sind Repository-Schnappschüsse und keine startfertigen Pakete.
3. Prüfe bei Bedarf die Prüfsumme:
   - Windows: `Get-FileHash <runtime.zip> -Algorithm SHA256`
   - Linux: `sha256sum <runtime.zip>`
4. Beende Minecraft oder den Server und kopiere den vollständigen Weltordner an einen unabhängigen Ort.
5. Installiere bei Bedarf [Python 3.12 für Windows](https://www.python.org/downloads/windows/). Python 3.11, 3.13 und 3.14 werden nicht unterstützt. Aktiviere bei der Installation den Python Launcher oder **Add Python to PATH**.
6. Entpacke das Runtime-ZIP, führe einmal `setup.bat` aus und starte den Editor danach mit `start.bat`.
7. Folge beim ersten Start dem Einrichtungsdialog und lade **Item-DB** und **Vanilla-Icons**. Du kannst den Schritt aufschieben und später über den Einrichtungshinweis oder unter **Werkzeuge** nachholen. Der Editor bringt nur einen mitgelieferten Item-Stand und keine Icons mit — ohne diesen Schritt fehlen Items neuerer Minecraft-Versionen und jeder Slot zeigt ein Ersatzsymbol.

Falls noch kein Release vorhanden ist, können erfahrene Nutzer die Source-Einrichtung weiter unten verwenden.

<table>
  <tr>
    <td width="50%">
      <a href="docs/assets/editor-overview.png">
        <img src="docs/assets/editor-overview.png" alt="Weltauswahl und Sicherheitsstatus">
      </a>
    </td>
    <td width="50%">
      <a href="docs/assets/editor-inventory.png">
        <img src="docs/assets/editor-inventory.png" alt="Beispielinventar">
      </a>
    </td>
  </tr>
</table>

## Warum es dieses Projekt gibt

Der Editor ist für einen privaten Bedrock-Server entstanden. Kleine Korrekturen an Inventar oder Spielerwerten bedeuteten jedes Mal, die Weltdateien an einen Windows-Rechner zu kopieren — für eine Routinekorrektur unverhältnismäßig viel Aufwand.

Ziel war, solche Anpassungen von jedem Gerät im selben Netz aus vornehmen zu können. Die Docker-Instanz läuft neben dem Server, die Weboberfläche funktioniert von Laptop, Tablet oder Handy — ohne Windows-Rechner und ohne lokale Kopie der Welt.

Diese Herkunft erklärt den Zuschnitt: ein geprüfter Satz von Spielerfeldern, bearbeitet bei beendeter Welt und mit Backup, statt eines allgemeinen Welteditors.

## Unterstützte Bereiche

| Bereich | Umfang |
|---|---|
| Inventar | Hotbar, Rucksack, Rüstung, Schildhand, Verschieben, Kopieren und Sammelaktionen |
| Endertruhe | Anzeigen und Bearbeiten einschließlich Transfers zwischen sichtbaren Bereichen |
| Spielerwerte | Gesundheit, Spielmodus, XP, Hunger, Sättigung, Position, Effekte und Fähigkeiten |
| Sicherheit | Backups vor Schreibvorgängen, Restore-Prüfungen, Revisionen, Schreibsperren und Welt-Locks |
| Spielertransfer | Versionierte Migration lokal ↔ Multiplayer sowie vollständiger `.mcbe-player.zip`-Import/-Export |
| Icons | Vanilla-Icon-Download, lokale Ressourcenpakete, `.mcpack`, `.zip` und eigene Icon-Ordner |
| Mounts | Experimentelle Erzeugung von Pferden, Eseln, Maultieren, Skelettpferden und Kamelen |
| Diagnose | Weltstatus, Runtime-Prüfungen, Berichte und privater Spieler-Rohdatenexport |

Die App ist kein öffentlicher Hostingdienst, kein Server-Administrationspanel und kein uneingeschränkter Roh-NBT-Editor.

## Lokaler Windows-Start

Der lokale Modus benötigt **Python 3.12**, da die nativen Amulet-Abhängigkeiten versionsgebunden sind.

Im Source-Verzeichnis oder entpackten Runtime-Paket:

```bat
setup.bat
start.bat
```

`setup.bat` erstellt `.venv` im Projektordner und installiert keine globalen Python-Pakete. Der Editor läuft auf `127.0.0.1:5000`; App-Daten liegen unter `data/`.

Administratorrechte sollten normalerweise nicht erforderlich sein. Falls eine sicher beendete Welt wegen Windows-Dateirechten nicht gespeichert werden kann, kann der Start als Administrator als Diagnosetest dienen. Eine laufende Welt wird dadurch nicht sicher bearbeitbar.

## Docker und vertrauenswürdiges LAN

Ziehe für ein veröffentlichtes Release den passenden versionsspezifischen Tag. Ersetze `X.Y.Z` durch die Version auf der [Releases-Seite](https://github.com/dadeeen/MCBE_Inventory_Editor/releases); der Docker-Tag lässt das führende `v` des Git-Tags weg:

```bash
docker pull ghcr.io/dadeeen/mcbe-inventory-editor:X.Y.Z
```

Stabile Versionstags aktualisieren zusätzlich den passenden Minor-Tag (zum Beispiel `0.5`) und `latest`. Vorabversionen veröffentlichen nur ihre vollständigen Versions- und Revisionstags und bewegen `latest` nie. Bevorzuge für Instanzen den exakten Versionstag, da `latest` und Minor-Tags bewusst veränderlich sind.

Alternativ den aktuellen Stand selbst bauen:

```bash
docker build -t mcbe-inventory-editor:local .
```

Minimales Compose-Beispiel mit dem veröffentlichten Image:

```yaml
services:
  mcbe-editor:
    image: ghcr.io/dadeeen/mcbe-inventory-editor:X.Y.Z
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

Das mitgelieferte [`docker-compose.example.yml`](docker-compose.example.yml) ist das entsprechende Beispiel für den Selbstbau und baut den aktuellen Stand, statt von GHCR zu ziehen.

Lege beim ersten Öffnen ein Passwort fest oder bestätige ausdrücklich den passwortlosen Betrieb in einem vertrauenswürdigen Netz. Schütze den Port mit Firewallregeln und richte weder öffentlichen Ingress noch öffentliche Tunnel ein.

Wichtiges Docker-Verhalten:

- Welten werden unter `/worlds` gelesen; dauerhafte App-Daten und Backups liegen unter `/data`.
- `MCBE_REQUIRE_SERVER_OFFLINE=true` ist Standard. Ein erreichbarer konfigurierter Bedrock-Server blockiert Schreibvorgänge; ein unbekannter Status verlangt eine Bestätigung.
- `MCBE_READ_ONLY=true` schaltet die App in den schreibgeschützten Viewer-Modus. Binde für eine echte Viewer-Instanz zusätzlich `/worlds:ro` ein; Docker `read_only: true` schützt eingebundene Welten nicht.
- Binde bei schreibfähigen Instanzen den gemeinsamen übergeordneten Weltordner unter `/worlds` ein, nicht nur eine einzelne Welt. Restore-Staging und Rollback benötigen Zugriff auf Geschwisterpfade.
- Der Container läuft ohne Root-Rechte als UID/GID `10001`; der Hostordner muss die erforderlichen Rechte gewähren. Ein `:rw`-Mount allein genügt nicht — richte das **vor** dem ersten Speichern ein, siehe [Schreibrechte für Docker-Welten](#schreibrechte-für-docker-welten).
- Der Einrichtungshinweis beim ersten Start gilt auch hier: **Item-DB** und **Vanilla-Icons** liegen unter `/data` — halte dieses Volume persistent und erlaube dem Container ausgehendes HTTPS.
- Ein erfolgreiches vollständiges Item-DB-Update legt einen Verifikationsbeleg neben der Datenbank unter `/data` ab. Er ist an genau diese Datenbankdatei und ihre Quellmetadaten gebunden: Ein Browserwechsel erhält den geprüften Zustand, während das Löschen oder Ersetzen von `/data` bewusst ein neues vollständiges Item-DB-Update erfordert.

### Schreibrechte für Docker-Welten

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

Die Default-ACL auf den Verzeichnissen sorgt dafür, dass neu angelegte Dateien und Unterordner den Editorzugriff erben. Binde weiterhin den gemeinsamen Weltordner und nicht nur eine einzelne Welt ein, damit Restore und Rollback ihre sicheren temporären Geschwisterpfade anlegen können.

Prüfe anschließend mit dem tatsächlichen Weltordner:

```bash
docker exec mcbe-editor sh -lc '
id
test -w /worlds/MeineWelt/db &&
  echo "Welt-Datenbank ist beschreibbar" ||
  echo "Welt-Datenbank ist NICHT beschreibbar"
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

`docker-compose.viewer.example.yml` zeigt eine gehärtete Viewer-Konfiguration. Lokale Hilfsskripte liegen unter `scripts/docker/`.

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

Für private CLI-Diagnosen:

```bash
python scripts/export_player_raws.py list --world "/PFAD/ZUR/WELT"
python scripts/export_player_raws.py export --world "/PFAD/ZUR/WELT" --all --bundle-zip
```

## Experimentelle Mounts

Die Mount-Ansicht kann Pferde, Esel, Maultiere, Skelettpferde und Kamele nahe dem Spieler in der Oberwelt vormerken. Die Platzierung wird anhand dekodierter Geländedaten geprüft:

- grüne Kandidaten werden akzeptiert;
- gelbe Kandidaten konnten nicht sicher bestätigt werden und benötigen eine ausdrückliche Bestätigung;
- rote Kandidaten werden serverseitig abgelehnt.

Das Vormerken schreibt noch nichts in die Welt. Der bestätigte Workspace-Speichervorgang erstellt ein Backup und schreibt Spieler- und Mount-Datensätze gemeinsam. Gelände, Dimensionen, Add-ons und künftige Bedrock-Versionen sind nicht vollständig abgedeckt; teste die Funktion zuerst auf entbehrlichen Weltkopien.

## Datensicherheit und Datenschutz

Der Editor lässt nicht unterstützte Bedrock- und Add-on-Daten unangetastet, statt sich wie ein vollständiger Roh-NBT-Editor zu verhalten. Unbekannte Formate können Annahmen dennoch ungültig machen. Kein Backup und keine Validierung können die semantische Korrektheit jeder Welt oder künftigen Minecraft-Version garantieren.

Wesentliche Schutzmaßnahmen:

- Der lokale Modus bindet standardmäßig nur an `127.0.0.1`.
- Das Bearbeiten von Welten funktioniert vollständig offline. Ausgehendes HTTPS wird nur für die von dir ausgelösten Updates von **Item-DB** und **Vanilla-Icons** genutzt; dafür gilt eine feste Host-Liste für GitHub und `learn.microsoft.com`. Optional prüft `MCBE_STARTUP_NETWORK_CHECK=true` beim Start, ob diese Hosts erreichbar sind. Die Anwendung kontaktiert `minecraft.wiki` zur Laufzeit nicht.
- Docker/LAN verlangt bei der Ersteinrichtung eine bewusste Passwortentscheidung.
- Ändernde Requests verwenden CSRF-/Origin-Prüfungen und geladene Spielerrevisionen.
- Weltzugriffe werden serialisiert und prüfen den Serverstatus unmittelbar vor dem Schreiben erneut.
- No-op-Speichervorgänge schreiben nichts und erzeugen kein Backup.
- Restore erstellt ein Pre-Restore-Backup und prüft das Archiv vor dem Austausch.
- Audit-Logs, Diagnoseberichte, Backups, Welten und Spielerexporte können private oder identifizierende Informationen enthalten. Veröffentliche sie nicht ohne sorgfältige Bereinigung.

Hinweise zum Melden von Sicherheitslücken und zur unterstützten Sicherheitsgrenze stehen in [SECURITY.de.md](SECURITY.de.md).

Runtime-Daten gehören weder ins Repository noch in Release-Archive. Typische Orte:

```text
data/                  # lokaler Modus
/data/                 # Docker-Modus
/data/backups/         # Docker-Backups
/data/audit/events.jsonl
```

## Kompatibilität und Grenzen

- Die Anwendung ist für lokale oder vertrauenswürdige LAN-Nutzung gedacht, nicht für öffentliche Bereitstellung.
- Echte Welten dürfen nur bearbeitet werden, während Minecraft oder der Server beendet ist.
- Bedrock-Updates, Add-ons, undurchsichtige NBT-Daten und ungewöhnliche LevelDB-Strukturen können außerhalb dessen liegen, wofür der Editor ausgelegt ist.
- Die experimentelle Mount-Platzierung bildet nicht die vollständige Minecraft-Kollisionsphysik ab.
- Runtime-ZIPs besitzen eine SHA-256-Prüfsumme und ein internes Dateimanifest, aber keine unabhängige kryptografische Signatur.

## Entwicklung und Lizenz

Fehlerberichte und Beiträge sind willkommen. Verwende synthetische Daten und bereinigte Logs; hänge niemals echte Welten, Backups, Spielerexporte, Audit-Exporte, Spielernamen, private Pfade oder Zugangsdaten an.

Hinweise für Mitwirkende, Tests, Fixtures und Release-Hygiene stehen in [docs/development.md auf GitHub](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md). Interne Speicherinvarianten stehen in [docs/save_contract.md](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/save_contract.md).

Der eigene Projektcode steht unter der [MIT-Lizenz](LICENSE). Die Anwendung verwendet `amulet_nbt` und `amulet_leveldb` unter der Amulet Team License 1.0.0 (PolyForm-Shield- und Noncommercial-Bedingungen mit einer begrenzten Ausnahme für kommerzielle Nutzung ausschließlich zu Bildungszwecken). Dies ist keine klassische Open-Source-Lizenz und schränkt die zulässige Nutzung ein; maßgeblich sind die Lizenztexte der vorgelagerten Pakete. `amulet_mutf8` steht unter der MIT-Lizenz.

Minecraft-Inhalte fallen nicht unter die Lizenz dieses Projekts. Das Repository enthält einen aus `Mojang/bedrock-samples` und Microsoft Learn erzeugten Item-Datenstand; Vanilla-Icons werden nur auf Anforderung heruntergeladen und nicht mitgeliefert. Die Herkunft der lokal gepflegten Verzauberungs-Maximalstufen ist in [docs/development.md auf GitHub](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md#bundled-item-database-and-enchantment-max-levels) dokumentiert. Minecraft und seine Inhalte gehören Mojang Studios/Microsoft und unterliegen deren Bedingungen.

Wichtige vorgelagerte Projekte sind das [Amulet Team](https://github.com/Amulet-Team), [NumPy](https://numpy.org/), Flask und das Pallets-Team sowie das [Minecraft Wiki](https://minecraft.wiki/) als Referenz für manuell geprüfte Spielmechaniken.
