# DECT plays Pokémon (DPP)

Kollaboratives Pokémon Feuerrot spielen via DECT phone.
Per Anruf können Spieler:innen inputs an das emulierte Spiel geben.
Inputs werden durch Wahltasten (1-9) generiert.

## Spielablauf

Alles läuft auf einem Gerät (z.B. Raspberry Pi), welches per HDMI+Beamer den
game state zeigt und sich per Ethernet-Kabel bei Eventphone registriert.

Spieler rufen bei der Pokémon hotline an, und ihre Tasteneingaben werden in
Emulator-inputs übersetzt. Auf einem Beamer zeigt das Pi eine GUI mit Emulator,
Telefonnummer, stats in Pokémon und stats über DPP.

Das Spiel wird alle X Zeiteinheiten gesnapshotted und diese Snapshots irgendwo
gespeichert.
Admins können einen Rollback initiieren, falls z.B. jmd ein softlock produziert.
Das ganze wird in einer Tabelle, die metadaten und eine Referenz auf den
gesnapshotteten state hat, gespeichert.

Alle inputs werden in einer separaten Tabelle gespeichert, und in einem Format,
sodass sie replayed werden können. Und wir können dann coole Statistiken
daraus generieren.

## Technische Fragen

* Wie nehmen wir automatisiert Anrufe entgegen und verarbeiten deren Knopfdrücke?
    * A: https://github.com/eventphone/hotline
* Welchen Emulator verwenden wir?
* Wie funktioniert das ganze wrt. concurrency?
* Wie gross ist X?
* Wie programmieren wir das GUI?
* Können wir badges an Anrufer vergeben?

## Design

```
                     on (re-)connect
                  game state + metadata                                     |
+----------+   -------------------------->  +------------+      DMTF   ------
| Server   |                                | Client     |    <------- |Dect|
+----------+   <--------------------------  +------------+             ------
             snapshot of game state, inputs
                       periodically
```

Auf dem Server sind:
* Metadaten
* Snapshots (?)
* Alle Inputs

Auf dem Client ist:
* Emulator
* Inputs seit letztem Snapshot
* DECT-Logik

## ToDos

- [ ] E-Mail an das Eventphone team bzgl. gewünschter Nummer + Funktionalität.
- [ ] E-Mail an das Assembly team bzgl. geeignetem Platz mit Leinwand.
- [ ] Programmierung des DECT/SIP mechanismuses
    - [ ] Wie testet man das?
