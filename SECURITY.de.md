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

Eröffne für eine ungepatchte Sicherheitslücke kein öffentliches Issue. Hänge niemals echte Welten, Backups, Spieler- oder Audit-Exporte, Roh-NBT-Daten, Spielernamen, XUID-ähnliche Kennungen, private Pfade, IP-Adressen, Benutzernamen, Token, Passwörter, Cookies oder Sitzungsdaten an.

Nenne nur die erforderlichen Informationen:

- betroffene Version oder Commit und Betriebsmodus;
- Sicherheitsauswirkung und notwendige Angriffsbedingungen;
- minimale Reproduktionsschritte mit synthetischen Daten;
- bereinigte Logs oder Request-Metadaten.

Falls die private Meldung nicht verfügbar ist, eröffne ein minimales öffentliches Issue mit der Bitte um einen privaten Kontaktweg, ohne die Sicherheitslücke offenzulegen.

Wir streben eine Bestätigung innerhalb von drei Arbeitstagen und eine erste Bewertung innerhalb von sieben Arbeitstagen an. Die Behebung hängt von Schweregrad und Komplexität ab. Gib uns vor einer öffentlichen Offenlegung Zeit für eine koordinierte Korrektur und ein Release.

Normale Fehler gehören in den Issue-Tracker. Verwende den privaten Kanal für Datenverlustrisiken, Umgehungen von Authentifizierung oder Autorisierung, unsichere Pfadverarbeitung, die Offenlegung geheimer oder privater Daten und aus der Ferne auslösbare Schreibvorgänge.

## Sicherheitsgrenze

Der Editor liest und verändert Bedrock-NBT und LevelDB direkt. Backups, Validierung, Revisionen, Dateisperren, Schreibsperren, CSRF-/Origin-Prüfungen und Authentifizierung reduzieren Risiken, können aber nicht die Korrektheit für jede Bedrock-Version, jedes Add-on und jede ungewöhnliche Weltstruktur garantieren.

Die unterstützte Grenze umfasst:

- den lokalen Modus auf `127.0.0.1`; oder
- eine authentifizierte Instanz, die nur aus einem vertrauenswürdigen LAN oder privaten Netz erreichbar ist;
- vollständig beendete Welten vor Schreibvorgängen;
- vollständige, unabhängige Weltkopien außerhalb der vom Editor verwalteten Pfade.

Öffentliches Hosting, nicht vertrauenswürdiger Mehrbenutzerzugriff, breite Host-Dateisystem-Mounts und direkter Internetzugang liegen außerhalb der unterstützten Grenze. Ein Reverse Proxy ändert diese Grenze nicht.

Beende Minecraft oder den Server vor jeder Bearbeitung und erstelle eine vollständige Kopie außerhalb des eingebundenen Weltordners und von `MCBE_BACKUP_ROOT`. Behalte sie, bis das Ergebnis in Minecraft geprüft wurde.

## Wesentliche Deployment-Regeln

- Aktiviere für LAN-Nutzung den Passwortschutz.
- Belasse `MCBE_TRUST_PROXY_HEADERS=false`, sofern ein vertrauenswürdiger Reverse Proxy nicht der einzige Weg zur App ist.
- Belasse `MCBE_REQUIRE_SERVER_OFFLINE=true` für echte Serverwelten und konfiguriere `MCBE_SERVER_HOST`.
- Behandle `MCBE_REQUIRE_SERVER_OFFLINE=false` als ausdrückliche unsichere Ausnahme ausschließlich für beendete Kopien oder Archive.
- Verwende für Viewer sowohl `MCBE_READ_ONLY=true` als auch ein `/worlds:ro`-Volume. Docker `read_only: true` schützt nur das Root-Dateisystem des Containers.
- Binde nur den erforderlichen übergeordneten Weltordner ein, niemals `/`, `/home` oder ein gesamtes NAS.
- Gewähre dem nicht privilegierten Containerprozess gezielte Rechte als UID `10001` oder über eine dedizierte gemeinsame Gruppe. Die konkreten ACL- und Gruppenvarianten stehen in `README.de.md` unter „Schreibrechte für Docker-Welten“.
- Verwende weder `chmod 777` noch `privileged: true`, Root-Betrieb oder das Löschen beziehungsweise Umgehen von LevelDB-Sperren als Berechtigungslösung.
- Halte `/data` privat und persistent. Es enthält Einrichtungszustand, Backups und möglicherweise Audit-Daten.
- Verwende `MCBE_FAIL_ON_INSECURE_CONFIG=true`, wenn ein nicht authentifizierter breiter Bind den Start abbrechen soll.

Schreibvorgänge prüfen den Server-Guard unmittelbar vor dem abschließenden Dateisystem- oder LevelDB-Zugriff erneut. Ein unbekannter Status kann eine ausdrückliche Bestätigung verlangen; ein später als online erkannter Server blockiert den Schreibvorgang weiterhin.

## Private Daten und Diagnosen

Echte Welten, Backups, `.mcbe-player.zip`-Dateien, Roh-NBT-Daten, Diagnoseberichte und Audit-Exporte müssen als privat behandelt werden. Das Umbenennen einer Welt oder Löschen ihres Icons anonymisiert keine LevelDB-Datensätze.

Das optionale Audit-Log kann enthalten:

- entfernte IP-Adressen und konfigurierte Benutzernamen;
- Weltordnernamen und stabile Hashes normalisierter Weltpfade;
- gekürzte Spielerschlüssel-Vorschauen und Spielerschlüssel-Hashes;
- Aktionsnamen, Ergebnisse, Anforderungskennungen und bereinigte Fehlerdetails.

Hashes und Kürzungen reduzieren Risiken, sind aber keine Anonymisierung. Weltnamen, IP-Adressen, Benutzernamen, Anforderungsmetadaten und stabile Hashes können weiterhin eine Person, ein Gerät oder eine Installation identifizieren. Veröffentliche Audit-Dateien oder Exporte nicht ohne manuelle Prüfung und zweckgebundene Bereinigung.

Geheimnisse, CSRF-Token, Passwörter, Sitzungswerte und erkannte vollständige Pfade werden vor der Audit-Speicherung redigiert oder reduziert. Dadurch werden die Logs nicht zu öffentlichen Daten. Unter POSIX beschränkt die App neu erstellte Setup- und Audit-Dateien auf den Eigentümer; unter Windows bleiben die ACLs des umgebenden Verzeichnisses maßgeblich.

Private Fixture-Welten gehören ausschließlich unter `fixtures/private/`; dieser Ordner wird ignoriert und aus Releases ausgeschlossen. Öffentliche Fixtures benötigen eine LevelDB-/NBT-gerechte Anonymisierung und eine manuelle Prüfung. Der unterstützte Scanner-Fixture-Generator entfernt die ursprünglichen LevelDB-Dateien.

## Abhängigkeiten und Prüfung

Lokale und Release-Umgebungen verwenden hashgebundene Abhängigkeiten für Python 3.12. Maßgeblich sind `pyproject.toml` und die Lockfiles; Versionen werden in dieser Richtlinie nicht dupliziert.

Vollständige lokale Sicherheitsprüfung. Führe zuerst einmal `setup.bat` aus, falls `.venv` noch nicht existiert; das erstellt die Umgebung mit Python 3.12. Die Befehle rufen diesen Interpreter direkt auf, da ein globaler die Entwicklungsabhängigkeiten systemweit installieren würde:

```bash
.venv/Scripts/python -m pip install --require-hashes -r requirements/bootstrap.lock
.venv/Scripts/python -m pip install --require-hashes -r requirements/dev.lock
.venv/Scripts/python scripts/security_check.py --require-pip-audit
```

Unter Linux und macOS lautet der Interpreter `.venv/bin/python`.

Abhängigkeitsfunde sind Release-Signale, kein Laufzeitschutz. Aktualisiere betroffene Pakete gezielt und wiederhole die vollständigen Test- und Release-Prüfungen; führe keine breiten automatischen Upgrades aus.

Normales Bearbeiten benötigt keinen ausgehenden Internetzugriff. Der optionale Item-Daten-Updater verwendet zugelassene HTTPS-Quellen und Größenlimits. Fehlender Netzwerkzugriff verhindert den Start nicht.

## Releases und Wiederherstellung

Offizielle Runtime-Pakete werden ausschließlich über die [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases) des ursprünglichen Repositorys veröffentlicht. Versionierte Runtime-ZIPs enthalten eine SHA-256-Prüfsumme und ein Dateimanifest. Diese erkennen Übertragungsfehler oder Änderungen, sind aber keine unabhängige kryptografische Signatur.

App-Backups werden vor einem Restore auf technische Lesbarkeit geprüft. Diese Prüfung kann nicht bestätigen, dass eine Welt semantisch korrekt oder mit einer bestimmten Minecraft-Version kompatibel ist. Die unabhängige Weltkopie bleibt die letzte Wiederherstellungsgrenze.

Gewährleistung und Haftung richten sich für den eigenen Projektcode nach dem genauen Text der [MIT-Lizenz](LICENSE). Gebündelte Amulet-Komponenten besitzen eigene, restriktivere Lizenzbedingungen.
