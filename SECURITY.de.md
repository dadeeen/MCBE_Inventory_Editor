# Sicherheitsrichtlinie

[🇬🇧 English](SECURITY.md) | **🇩🇪 Deutsch**

Der Minecraft Bedrock Inventory Editor ist für die lokale Nutzung und vertrauenswürdige LAN-Umgebungen mit eigenen Welten gedacht. Er ist nicht als öffentlicher Internetdienst konzipiert.

## Unterstützte Versionen

| Version | Unterstützung |
|---|---|
| Aktuelles veröffentlichtes [GitHub Release](https://github.com/dadeeen/MCBE_Inventory_Editor/releases) | Unterstützt |
| Aktueller `main`-Branch | Nach Möglichkeit; Entwicklungsstand |
| Ältere Releases und Commits | Nicht unterstützt |

## Sicherheitslücke melden

Melde vermutete Sicherheitslücken privat über GitHubs Formular [Report a vulnerability](https://github.com/dadeeen/MCBE_Inventory_Editor/security/advisories/new).

Lege eine ungepatchte Sicherheitslücke nicht in einem öffentlichen Issue offen. Verwende synthetische Beispiele; hänge niemals echte Welten, Backups, rohe Spielerdaten, Zugangsdaten oder ungeprüfte Logs an. Siehe [Private Daten und Diagnosen](#private-daten-und-diagnosen).

Nenne nur die erforderlichen Informationen:

- betroffene Version oder Commit und Betriebsmodus;
- Sicherheitsauswirkung und notwendige Angriffsbedingungen;
- minimale Reproduktionsschritte mit synthetischen Daten;
- bereinigte Logs oder Request-Metadaten.

Falls die private Meldung nicht verfügbar ist, eröffne ein minimales öffentliches Issue mit der Bitte um einen privaten Kontaktweg, ohne die Sicherheitslücke offenzulegen.

Wir streben eine Bestätigung innerhalb von drei Arbeitstagen und eine erste Bewertung innerhalb von sieben Arbeitstagen an. Die Behebung hängt von Schweregrad und Komplexität ab. Gib uns vor einer öffentlichen Offenlegung Zeit für eine koordinierte Korrektur und ein Release.

Normale Fehler gehören in den Issue-Tracker. Verwende den privaten Kanal für Datenverlustrisiken, Umgehungen von Authentifizierung oder Autorisierung, unsichere Pfadverarbeitung, die Offenlegung geheimer oder privater Daten und aus der Ferne auslösbare Schreibvorgänge.

## Sicherheitsgrenze

Der Editor verändert Bedrock-NBT und LevelDB direkt. Seine Schutzmaßnahmen können die Kompatibilität mit jeder Bedrock-Version, jedem Add-on und jeder ungewöhnlichen Weltstruktur nicht garantieren.

Die unterstützte Grenze umfasst:

- den lokalen Modus auf `127.0.0.1`; oder
- eine authentifizierte Instanz, die nur aus einem vertrauenswürdigen LAN oder privaten Netz erreichbar ist;
- vollständig beendete Welten mit unabhängigen Sicherungskopien.

Öffentliches Hosting, nicht vertrauenswürdiger Mehrbenutzerzugriff, breite Host-Dateisystem-Mounts und direkter Zugriff aus dem Internet liegen außerhalb der unterstützten Grenze. Ein Reverse Proxy ändert diese Grenze nicht.

Beende Minecraft oder den Server vor jeder Bearbeitung und erstelle eine vollständige Kopie außerhalb des eingebundenen Weltordners und von `MCBE_BACKUP_ROOT`. Behalte sie, bis das Ergebnis in Minecraft geprüft wurde.

Editor-Backups sind eine zusätzliche Absicherung. Ihre Konsistenz- und Archivprüfungen garantieren weder eine atomare Momentaufnahme einer laufenden Welt noch deren Verwendbarkeit in Minecraft. Der Schutz vor Stromausfällen hängt auch von Betriebssystem, Dateisystem und Datenträger ab. Technische Grenzen beschreibt der [Backup- und Restore-Vertrag](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/save_contract.md#backups-and-restore).

## Wesentliche Deployment-Regeln

- Aktiviere für LAN-Nutzung den Passwortschutz.
- Belasse `MCBE_TRUST_PROXY_HEADERS=false`, sofern ein vertrauenswürdiger Reverse Proxy nicht der einzige Weg zur App ist.
- Loopback-Anfragen sind standardmäßig auf lokale Hostnamen begrenzt. Setze für LAN/Docker oder einen vertrauenswürdigen Reverse Proxy `MCBE_TRUSTED_HOSTS` auf die erwarteten Hostnamen (kommasepariert, ohne URL-Schema, Pfad oder Port), oder prüfe diese am Proxy. Das ist unabhängig von `MCBE_ALLOWED_ORIGINS` und dem CSRF-Schutz.
- Belasse `MCBE_REQUIRE_SERVER_OFFLINE=true` für echte Serverwelten und konfiguriere `MCBE_SERVER_HOST`. Bei einem NetherNet-Server braucht der Editor zusätzlich TCP-Zugriff auf den Serverport.
- Behandle `MCBE_REQUIRE_SERVER_OFFLINE=false` als ausdrückliche unsichere Ausnahme ausschließlich für beendete Kopien oder Archive.
- Verwende für Viewer sowohl `MCBE_READ_ONLY=true` als auch ein `/worlds:ro`-Volume. Docker `read_only: true` schützt nur das Root-Dateisystem des Containers.
- Binde nur den erforderlichen übergeordneten Weltordner ein, niemals `/`, `/home` oder ein gesamtes NAS.
- Gewähre dem nicht privilegierten Containerprozess gezielte Rechte als UID `10001` oder über eine dedizierte gemeinsame Gruppe. Die konkreten ACL- und Gruppenvarianten stehen unter [Schreibrechte für Docker-Welten](README.de.md#schreibrechte-für-docker-welten).
- Verwende weder `chmod 777` noch `privileged: true`, Root-Betrieb oder das Löschen beziehungsweise Umgehen von LevelDB-Sperren als Berechtigungslösung.
- Halte `/data` privat und persistent. Es enthält Einrichtungszustand, Backups und möglicherweise Audit-Daten.
- Verwende `MCBE_FAIL_ON_INSECURE_CONFIG=true`, wenn ein nicht authentifizierter breiter Bind den Start abbrechen soll.

Dateisperren allein beweisen nicht, dass ein Bedrock-Server beendet ist. Lass die Serverstatus-Prüfung konfiguriert: Sie prüft unmittelbar vor dem Schreiben erneut. Ein unbekannter Status kann eine Bestätigung verlangen; ein als online erkannter Server blockiert den Schreibvorgang weiterhin.

Der Editor schreibt nicht in unvollständige oder widersprüchliche Datenbanken und repariert sie nicht. Meldet ein Speichern einen unbekannten Ausgang oder ein fehlgeschlagenes Zurücksetzen, behalte das Backup und lade die Welt neu, bevor du weiter bearbeitest: Daten können bereits geschrieben worden sein.

## Private Daten und Diagnosen

Echte Welten, Backups, `.mcbe-player.zip`-Dateien, Roh-NBT-Daten, Diagnoseberichte und Audit-Exporte müssen als privat behandelt werden. Das Umbenennen einer Welt oder Löschen ihres Icons anonymisiert keine LevelDB-Datensätze. Laufzeitdaten unter `data`, einschließlich Desktop-Profilen und Logs, gehören nicht in Releases.

Audit-Logs können IP-Adressen, Benutzernamen, Weltnamen, Pfad- und Spielerschlüssel-Hashes, gekürzte Spielerschlüssel sowie Aktionen, Ergebnisse und Anfrage-/Fehlerdetails enthalten. Automatische Bereinigung, Hashes und Kürzungen anonymisieren diese Daten nicht. Prüfe und bereinige Material vor jeder Weitergabe.

Details unerwarteter Ausnahmen bleiben im Server-Log, auf das die Anfrage-ID der Antwort (`X-Request-ID`) verweist; sie können private Pfade enthalten. Auch nutzergerichtete Meldungen können betroffene Dateien benennen. Unter POSIX sind neu erstellte Setup- und Audit-Dateien auf den Eigentümer beschränkt; unter Windows muss der umgebende Ordner durch passende ACLs geschützt sein.

Private Fixture-Welten gehören ausschließlich unter `fixtures/private/`; dieser Ordner wird ignoriert und aus Releases ausgeschlossen. Öffentliche Fixtures benötigen eine LevelDB-/NBT-gerechte Anonymisierung und manuelle Prüfung; siehe die [Fixture-Regeln](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/tests/fixtures/README.md) und den [Vertrag für isolierte Entity-Datensätze](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/tests/data/README.md).

## Abhängigkeiten und Prüfung

Abhängigkeiten sind für Python 3.12–3.14 hashgebunden; maßgeblich sind `pyproject.toml` und die Lockfiles. Das Windows-Browser-Setup und Docker benötigen vorgefertigte Pakete ohne automatischen Quellbau als Ersatz. Der portable Desktop enthält Python und verwendet die installierte WebView2 Runtime. Build-Details stehen im [Abhängigkeitsleitfaden](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/requirements/README.md) und in der [Desktop-Dokumentation](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/desktop.md).

Mitwirkende sollten betroffene Pakete gezielt aktualisieren und die [Test- und Abhängigkeitsprüfungen](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md#local-check-round) in der Entwicklungsumgebung des Quellcode-Checkouts ausführen. Audits bieten keinen Laufzeitschutz; vermeide breite automatische Upgrades.

Normales Bearbeiten und der Start benötigen keinen ausgehenden Internetzugriff. Optionale Item-Daten- und Icon-Downloads verwenden zugelassene HTTPS-Quellen und Größenlimits; konfigurierte Serverstatus-Prüfungen kontaktieren den Server.

## Releases und Wiederherstellung

Offizielle Browser- und Desktop-ZIPs werden über die [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases) des ursprünglichen Repositorys veröffentlicht; Docker-Images verwenden `ghcr.io/dadeeen/mcbe-inventory-editor`. Jedes Release-ZIP besitzt eine separate SHA-256-Prüfsummendatei und enthält ein Dateimanifest. Diese erkennen Übertragungsfehler oder Änderungen, sind aber keine unabhängige kryptografische Signatur.

Gewährleistung und Haftung richten sich für den eigenen Projektcode nach der [MIT-Lizenz](LICENSE). Abhängigkeiten besitzen eigene Lizenzbedingungen.

### Unterbrochene Wiederherstellungen

Beim Start bleibt die Wiederherstellung zurückgestellt, solange der Serverstatus unbekannt oder online ist. Beende Minecraft und den Bedrock-Server. Behalte Welt, Backup, Restore-Journal und vorhandene Staging-/Rollback-Verzeichnisse; lösche sie nicht, um die Warnung zu beseitigen.

Verwende die **Browser-Runtime oder einen Quellcode-Checkout** mit eingerichteter Python-Umgebung. Prüfe aus deren Anwendungsverzeichnis den übergeordneten Weltordner:

```powershell
.venv/Scripts/python.exe -m mcbe_editor.restore_recovery "C:/PFAD/ZU/WELTEN"
```

Unter Linux/macOS verwendest du `.venv/bin/python`. Für einen laufenden Docker-Editor gelten dessen Containername und Containerpfade:

```bash
docker exec mcbe-editor python -m mcbe_editor.restore_recovery /worlds
```

**Desktop-EXE:** Schließe den Editor und verwende den enthaltenen Recovery-Befehl aus PowerShell:

```powershell
.\MCBEInventoryEditor.exe --recover "C:/PFAD/ZU/WELTEN"
```

Alle drei Befehle prüfen ausstehende Wiederherstellungen, ohne sie auszuführen. Wiederhole den Befehl erst mit `--confirm-server-stopped`, nachdem du den Server beendet und die gemeldeten Pfade geprüft hast. Read-only-Modus oder ein erkannt laufender Server blockieren Änderungen weiterhin. Mehrdeutige Welt-/Rollback-Kopien bleiben unverändert und müssen manuell beurteilt werden.

Behalte die Server- und Read-only-Einstellungen (`MCBE_SERVER_HOST`, `MCBE_SERVER_PORT`, `MCBE_READ_ONLY`) bei. Übernimm einen vorhandenen `--data-dir` aus dem Befehl einer Desktop-Warnung. Desktop-Ergebnisse stehen in der dortigen `restore-recovery.txt` (normalerweise `data/restore-recovery.txt`); behandle Berichte als privat. Die Desktop-Wiederherstellung benötigt weder eine separate Python-Installation noch WebView2. Weitere Optionen stehen in der [Desktop-Befehlsreferenz](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/desktop.md#command-line-limits).
