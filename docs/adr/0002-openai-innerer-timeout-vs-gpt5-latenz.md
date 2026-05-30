# OpenAI-Adapter braucht erhöhten inneren Timeout für gpt-5

Der OpenAI researcher-Adapter hat ZWEI Timeouts: den äußeren Subprozess-Timeout
(`timeout_seconds` in der Adapter-Config, Default 30) UND einen inneren urllib-Timeout
(`ORCHESTRATED_LOOP_OPENAI_TIMEOUT`, Default 60, `openai_researcher.py:47`). Der innere
greift zuerst.

Im echten Loop-Vertragsbeweis (2026-05-30) riss gpt-5 den 60s-Default: ein realer Call
dauerte 72s. Mit `fallback: false` scheiterte der Lauf hart (`The read operation timed out`)
statt still auf die lokale Rolle zurückzufallen — gewolltes Verhalten laut ADR 0001.

Entscheidung: Für echte gpt-5-Läufe `ORCHESTRATED_LOOP_OPENAI_TIMEOUT` auf >= 180 setzen
UND den äußeren `timeout_seconds` darüber (hier 200). Der äußere muss IMMER größer als der
innere sein, sonst killt der Subprozess-Timeout den Adapter mitten im laufenden Call.

## Trade-off

Höherer Timeout = längeres Warten auf einen hängenden Call, bevor er als Fehler gilt.
Akzeptabel, weil gpt-5-Latenz real schwankt (34s isoliert, 72s im Loop am selben Tag)
und ein zu knapper Timeout echte Erfolge fälschlich als Fehler wertet. Verwandt mit
Memory L8/L12: Real-Daten-Verhalten weicht von Default-Annahmen ab.
