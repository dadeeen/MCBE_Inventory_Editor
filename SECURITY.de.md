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

Jedes vom Editor erstellte Welt-Backup vergleicht die Quellmetadaten vor und nach der Erstellung und synchronisiert das fertige Archiv ausdrücklich vor der Veröffentlichung. Erkannte Änderungen und Synchronisierungsfehler brechen abhängige Schreibvorgänge ab. Der Metadatenvergleich ist keine atomare Momentaufnahme einer laufenden Welt; die Verzeichnissynchronisierung steht unter Windows und auf manchen Dateisystemen nicht zur Verfügung. Diese Maßnahmen gewährleisten keinen universellen Schutz vor Stromausfällen.

## Wesentliche Deployment-Regeln

- Aktiviere für LAN-Nutzung den Passwortschutz.
- Belasse `MCBE_TRUST_PROXY_HEADERS=false`, sofern ein vertrauenswürdiger Reverse Proxy nicht der einzige Weg zur App ist.
- Loopback-Anfragen sind standardmäßig auf lokale Hostnamen begrenzt. Setze für LAN/Docker oder einen ausdrücklich vertrauenswürdigen Reverse Proxy `MCBE_TRUSTED_HOSTS` auf die erwarteten Hostnamen (kommasepariert, ohne URL-Schema, Pfad oder Port), oder prüfe diese am Proxy. Das ist unabhängig von `MCBE_ALLOWED_ORIGINS` und dem CSRF-Schutz. Der integrierte Desktop deaktiviert Proxy-Header-Vertrauen immer und erzwingt seine eigene Loopback-Hostliste.
- Belasse `MCBE_REQUIRE_SERVER_OFFLINE=true` für echte Serverwelten und konfiguriere `MCBE_SERVER_HOST`. Bei einem NetherNet-Server braucht der Editor zusätzlich TCP-Zugriff auf den Serverport.
- Behandle `MCBE_REQUIRE_SERVER_OFFLINE=false` als ausdrückliche unsichere Ausnahme ausschließlich für beendete Kopien oder Archive.
- Verwende für Viewer sowohl `MCBE_READ_ONLY=true` als auch ein `/worlds:ro`-Volume. Docker `read_only: true` schützt nur das Root-Dateisystem des Containers.
- Binde nur den erforderlichen übergeordneten Weltordner ein, niemals `/`, `/home` oder ein gesamtes NAS.
- Gewähre dem nicht privilegierten Containerprozess gezielte Rechte als UID `10001` oder über eine dedizierte gemeinsame Gruppe. Die konkreten ACL- und Gruppenvarianten stehen unter [Schreibrechte für Docker-Welten](README.de.md#schreibrechte-für-docker-welten).
- Verwende weder `chmod 777` noch `privileged: true`, Root-Betrieb oder das Löschen beziehungsweise Umgehen von LevelDB-Sperren als Berechtigungslösung.
- Halte `/data` privat und persistent. Es enthält Einrichtungszustand, Backups und möglicherweise Audit-Daten.
- Verwende `MCBE_FAIL_ON_INSECURE_CONFIG=true`, wenn ein nicht authentifizierter breiter Bind den Start abbrechen soll.

Schreibvorgänge prüfen den Server-Guard unmittelbar vor dem abschließenden Dateisystem- oder LevelDB-Zugriff erneut. Ein unbekannter Status kann eine ausdrückliche Bestätigung verlangen; ein später als online erkannter Server blockiert den Schreibvorgang weiterhin.

Dateisperren allein beweisen nicht, dass ein Bedrock-Server beendet ist: BDS 1.26.51.1 unter Linux hält keinen LevelDB-`LOCK`. Beende den Server und lass die Serverstatus-Prüfung konfiguriert.

Der Editor schreibt nicht in unvollständige oder widersprüchliche Datenbanken und repariert keine Datenbanken. Meldet ein Speichern einen unbekannten Ausgang oder ein fehlgeschlagenes Zurücksetzen, behalte das zugehörige Backup und lade die Welt neu, bevor du weiter bearbeitest: Ein Teil der Daten kann schon auf dem Datenträger sein. Fehler, bei denen der Editor nachweisen kann, dass noch nichts geschrieben wurde, meldet er als gewöhnliche Ablehnung.

## Private Daten und Diagnosen

Echte Welten, Backups, `.mcbe-player.zip`-Dateien, Roh-NBT-Daten, Diagnoseberichte und Audit-Exporte müssen als privat behandelt werden. Das Umbenennen einer Welt oder Löschen ihres Icons anonymisiert keine LevelDB-Datensätze.

Das optionale Audit-Log kann enthalten:

- entfernte IP-Adressen und konfigurierte Benutzernamen;
- Weltordnernamen und stabile Hashes normalisierter Weltpfade;
- gekürzte Spielerschlüssel-Vorschauen und Spielerschlüssel-Hashes;
- Aktionsnamen, Ergebnisse, Anforderungskennungen und bereinigte Fehlerdetails.

Hashes und Kürzungen reduzieren Risiken, sind aber keine Anonymisierung. Weltnamen, IP-Adressen, Benutzernamen, Anforderungsmetadaten und stabile Hashes können weiterhin eine Person, ein Gerät oder eine Installation identifizieren. Veröffentliche Audit-Dateien oder Exporte nicht ohne manuelle Prüfung und zweckgebundene Bereinigung.

Geheimnisse, CSRF-Token, Passwörter, Sitzungswerte und erkannte vollständige Pfade werden vor der Audit-Speicherung redigiert oder reduziert. Dadurch werden die Logs nicht zu öffentlichen Daten. Unter POSIX beschränkt die App neu erstellte Setup- und Audit-Dateien auf den Eigentümer; unter Windows bleiben die ACLs des umgebenden Verzeichnisses maßgeblich.

Fehlerantworten nennen die fehlgeschlagene Aktion. Der Text einer unerwarteten Ausnahme, der lokale Pfade oder Interna enthalten kann, bleibt im Server-Log: Die Antwort nennt die Anfrage-ID, unter der das Log ihn führt (auch als Header `X-Request-ID`), und bei einem Betriebssystemfehler dessen Beschreibung ohne Pfad. Meldungen, die der Editor für Nutzer formuliert, etwa eine verweigerte Dateiberechtigung, und Hinweise auf Dateien, die von Hand entfernt werden müssen, erscheinen vollständig.

Private Fixture-Welten gehören ausschließlich unter `fixtures/private/`; dieser Ordner wird ignoriert und aus Releases ausgeschlossen. Öffentliche Fixtures benötigen eine LevelDB-/NBT-gerechte Anonymisierung und eine manuelle Prüfung. Der unterstützte Scanner-Fixture-Generator entfernt die ursprünglichen LevelDB-Dateien.

## Abhängigkeiten und Prüfung

Lokale und Release-Umgebungen verwenden hashgebundene Abhängigkeiten für Python 3.12–3.14. Maßgeblich sind `pyproject.toml` und die Lockfiles; Versionen werden in dieser Richtlinie nicht dupliziert.

Runtime-ZIPs enthalten den Python-Code für NBT und Bedrock-LevelDB ohne Amulet-Bibliotheken oder gebündelte LevelDB-Wheels. Windows-Setup und Docker installieren ausschließlich hashgeprüfte vorgefertigte Abhängigkeiten. CI prüft frische Umgebungen ohne native Referenzbibliotheken sowie separat die unabhängigen Amulet-Vergleichstests. Prüfe zusätzlich die veröffentlichte Prüfsumme des Release-ZIPs.

Das portable Windows-ZIP enthält CPython und seine Abhängigkeiten. Das Fenster verwendet die installierte WebView2 Evergreen Runtime sowie dieselbe lokale HTTP-API und dieselben Schreibsperren. Browser und Docker benötigen keine Desktop-Abhängigkeiten. Die Desktop-Build-Abhängigkeiten besitzen ein separates, auditiertes Hash-Lockfile; der Build erlaubt ausdrücklich das kleine reine Python-Quellarchiv `proxy-tools` in einer gebundenen Build-Umgebung. Die Anwendung installiert keine Abhängigkeiten auf dem Rechner des Nutzers. Halte `data` einschließlich WebView-Profil und Desktop-Log privat und außerhalb von Release-Archiven.

Mitwirkende führen die [lokale Prüfrunde und Abhängigkeitsprüfung](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md#local-check-round) in einem Quellcode-Checkout mit Entwicklungsumgebung aus. Diese Python-Befehle lassen sich nicht über die portable EXE starten. Verwende den Interpreter aus der Projekt-`.venv`, statt Entwicklungspakete global zu installieren.

Es gibt keinen automatischen Quellbau als Ersatz für fehlende Wheels. Docker lädt Abhängigkeiten in einer separaten Stufe mit Hashprüfung herunter und installiert sie im Runtime-Image ohne Netzwerkzugriff. Die zusätzlichen Referenz-Lockfiles sind nicht Teil der Runtime; ihr verpflichtender CI-Lauf prüft die tatsächlichen Imports und auditiert beide Lockfiles.

Abhängigkeitsfunde sind Release-Signale, kein Laufzeitschutz. Aktualisiere betroffene Pakete gezielt und wiederhole die vollständigen Test- und Release-Prüfungen; führe keine breiten automatischen Upgrades aus.

Normales Bearbeiten benötigt keinen ausgehenden Internetzugriff. Der optionale Item-Daten-Updater verwendet zugelassene HTTPS-Quellen und Größenlimits. Fehlender Netzwerkzugriff verhindert den Start nicht.

## Releases und Wiederherstellung

Offizielle Browser- und Desktop-ZIPs werden über die [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases) des ursprünglichen Repositorys veröffentlicht; Docker-Images verwenden `ghcr.io/dadeeen/mcbe-inventory-editor`. Jedes Release-ZIP besitzt eine separate SHA-256-Prüfsummendatei und enthält ein Dateimanifest. Diese erkennen Übertragungsfehler oder Änderungen, sind aber keine unabhängige kryptografische Signatur.

App-Backups werden vor einem Restore auf technische Lesbarkeit geprüft. Diese Prüfung kann nicht bestätigen, dass eine Welt semantisch korrekt oder mit einer bestimmten Minecraft-Version kompatibel ist. Die unabhängige Weltkopie bleibt die letzte Wiederherstellungsgrenze.

Gewährleistung und Haftung richten sich für den eigenen Projektcode nach dem genauen Text der [MIT-Lizenz](LICENSE). Abhängigkeiten, einschließlich der optionalen Amulet-Testreferenzen, besitzen eigene Lizenzbedingungen.

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

Die Prüfung lässt ausstehende Wiederherstellungen zurückgestellt. Prüfe die gemeldeten Pfade und bestätige, dass der Server beendet ist; wiederhole den Befehl dann mit `--confirm-server-stopped`. Read-only-Modus oder ein erkannt laufender Server blockieren Änderungen weiterhin. Mehrdeutige Welt-/Rollback-Kopien bleiben unverändert und müssen manuell beurteilt werden. Ohne Pfadangabe verwendet der Befehl die konfigurierten Suchorte dieser Installation.

**Desktop-EXE:** Schließe den Editor und verwende den enthaltenen Recovery-Befehl aus PowerShell:

```powershell
.\MCBEInventoryEditor.exe --recover "C:/PFAD/ZU/WELTEN"
```

Es gelten dieselben Prüfungen und Schreibschutzregeln. Ergänze `--confirm-server-stopped` erst, nachdem du den Server beendet und die Pfade geprüft hast. Behalte die Umgebungsvariablen für Server und Read-only-Modus (`MCBE_SERVER_HOST`, `MCBE_SERVER_PORT`, `MCBE_READ_ONLY`) bei. Der in einer Desktop-Warnung angebotene Befehl enthält den aktiven `--data-dir`; übernimm ihn. Ergebnisse und Hilfetext stehen in `restore-recovery.txt` in diesem Datenordner (normalerweise `data/restore-recovery.txt`). Für automatisierte Aufrufe setzt du `--recovery-report "C:/PFAD/ZUM/bericht.txt"` vor `--recover`, um den Berichtspfad festzulegen und den Ergebnisdialog zu unterdrücken. Die Wiederherstellung benötigt weder eine separate Python-Installation noch WebView2 Runtime. Behandle Recovery-Berichte als privat.
