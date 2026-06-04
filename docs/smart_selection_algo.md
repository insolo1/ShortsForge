# Алгоритмы смарт-отбора

## Общая база (все режимы)

### 1. Сборка фраз (`_build_phrases`)

Whisper отдаёт сегменты — куски текста с временными метками. Они склеиваются в **фразы**: если пауза между соседними сегментами < 1с — это одна фраза, если >= 1с — разрыв, новая фраза.

Фраза = `{start, end, words, duration, full_text}`

```
Вход: [{"start":0.5,"end":1.2,"text":"Привет"}, {"start":1.3,"end":2.0,"text":"мир"}, ...]
                                        ↓
               пауза 0.1с < 1с → одна фраза "Привет мир"
```

### 2. Скользящее окно

По временной шкале видео двигается окно шириной `short_length` с шагом `short_length // 2`.

**Пример для short_length = 45с:**

```
Окно 0:  [0.0 ────────── 45.0)
Окно 1:       [22.5 ──────── 67.5)
Окно 2:            [45.0 ─────── 90.0)
Окно 3:                 [67.5 ────── 112.5)
... и так до конца видео
```

Для каждого окна собираются все фразы, попавшие внутрь.

### 3. Скоринг (6 метрик → 0–100)

Для каждого окна считается:

| Метрика | Формула | Вес |
|---------|----------|-----|
| **Плотность текста** | `min(слов / 5, 1) × 25` | 25% |
| **Доля речи** | `min(speech_duration / short_length, 1) × 25` | 25% |
| **Длина фраз** | `min(avg_phrase_len / 20, 1) × 15` | 15% |
| **Разнообразие** | `unique_words / total_words × 15` | 15% |
| **Эмоции** | `min((!×3 + ?×2) / 10, 1) × 10` | 10% |
| **Вариативность темпа** | `min(std(phrase_lengths) / mean, 1) × 10` | 10% |

Итоговый score = сумма всех (нормированная метрика × вес).

### 4. Отбор непересекающихся

Все окна сортируются по score (убывание). Проходим сверху вниз:

- Если окно не пересекается ни с одним уже выбранным (`start < selected_end && end > selected_start`) — добавляем
- Если пересекается — пропускаем
- Как только набрали `shorts_count` — стоп

Если набрали меньше — **второй проход** по оставшимся с тем же правилом.

---

## Режим `off` — выключен

```
ВХОД: video_path, short_length, shorts_count
ДЕЙСТВИЕ: вызвать _default_segments()
         ↓
    Видео делится на shorts_count равных частей
    (длительность / shorts_count = длина одного сегмента)
         ↓
ВЫХОД: list[{start, end}]
```

Никакой транскрипции, никакого анализа. Просто арифметика.

---

## Режим `parts` — сетка

```
ВХОД: video_path, duration, short_length, shorts_count

ШАГ 1: Разделить видео на N частей
    parts = max(20, min(shorts_count, 200))
    part_len = duration / parts          // длительность одной части
    max_analyze = min(part_len, 1200)    // не больше 1200с на транскрипцию

ШАГ 2: Для каждой части p (0..N-1):
    start = p × part_len
    end   = min(start + max_analyze, duration)

    // Транскрибируем часть
    segments = whisper(video, start, end)

    // Добавляем все сегменты в общий пул
    all_segments += segments

    // Ищем 1 ЛУЧШИЙ сегмент в этой части
    best = _find_best_segments(part_len, short_length, 1, segments)
    // _find_best_segments сделает:
    //   - скользящее окно по part_len
    //   - посчитает score для каждой позиции
    //   - вернёт топ-1 непересекающийся

    Если best найден → результат[p] = best
    Иначе → результат[p] = середина части (заглушка)

ШАГ 3: Если len(результат) < shorts_count:
    Добрать из all_segments через _find_best_segments(глобально)

ВЫХОД: результат[:shorts_count]
```

**Иллюстрация для видео 600с, shorts_count=3, short_length=45с:**

```
parts = max(20, min(3, 200)) = 20
part_len = 600 / 20 = 30с

Часть 0 (0-30с)     → Whisper → _find_best → лучший в 0-30с → сегмент A
Часть 1 (30-60с)    → Whisper → _find_best → лучший в 30-60с → сегмент B
Часть 2 (60-90с)    → Whisper → _find_best → лучший в 60-90с → сегмент C
... (остальные 17 частей)

Результат: [A, B, C] — по одному из каждой первой трети
```

---

## Режим `global` — топ

```
ВХОД: video_path, duration, short_length, shorts_count

ШАГ 1: Разделить видео на N частей (только для транскрипции)
    parts = max(20, min(shorts_count, 200))
    part_len = duration / parts
    max_analyze = min(part_len, 1200)

ШАГ 2: Для каждой части p (0..N-1):
    start = p × part_len
    end   = min(start + max_analyze, duration)
    segments = whisper(video, start, end)

    // Все сегменты — в один candidates_pool (с пометкой score=0)
    candidates_pool += segments

ШАГ 3: Единственный вызов _find_best_segments на ВСЕХ сегментах:
    result = _find_best_segments(duration, short_length, shorts_count, candidates_pool)

    // _find_best_segments сделает:
    //   - скользящее окно по ВСЕЙ длительности (0..duration)
    //   - посчитает score для каждого окна
    //   - отсортирует всё глобально
    //   - отберёт top-N непересекающихся

ВЫХОД: result
```

**Иллюстрация для видео 600с, shorts_count=2, short_length=45с:**

```
Сканируем всё видео → all_segments

_find_best_segments:
  Окно  0-45с    → score 30
  Окно 22.5-67.5с→ score 25
  Окно 45-90с    → score 35
  ...
  Окно 200-245с  → score 92   ← ВЫБРАН (1)
  ...
  Окно 500-545с  → score 88   ← ВЫБРАН (2)
  ...

Результат: [200-245с, 500-545с] — два лучших независимо от того,
где в видео они находятся. Всё остальное (0-200с, 245-500с) — пропущено.
```

---

## Режим `hybrid` — гибрид

```
ВХОД: video_path, duration, short_length, shorts_count

ШАГ 1: Разделить на части (как в parts)

ШАГ 2: Для каждой части p (0..N-1):
    start = p × part_len
    end   = min(start + max_analyze, duration)
    segments = whisper(video, start, end)

    // В отличие от parts — берём TOP-3 из каждой части
    best3 = _find_best_segments(part_len, short_length, 3, segments)
    // _find_best_segments вернёт 3 лучших непересекающихся в этой части

    candidates += best3    // все топ-3 со всего видео в один список

ШАГ 3: Глобальная сортировка всех кандидатов:
    candidates.sort(by=score, reverse=True)

ШАГ 4: Отбор непересекающихся (как в _find_best_segments, но без скользящего окна):
    result = []
    for c in candidates:
        if c не пересекается ни с кем в result:
            result += c
        if len(result) >= shorts_count:
            break

ВЫХОД: result
```

**Иллюстрация для видео 600с, shorts_count=3, short_length=45с, parts=20, part_len=30с:**

```
Часть 0 (0-30с):     _find_best(3) → [A(score 80), B(score 45), C(score 30)]
Часть 1 (30-60с):    _find_best(3) → [D(score 70), E(score 60), F(score 20)]
Часть 2 (60-90с):    _find_best(3) → [G(score 90), H(score 50), I(score 25)]
... (остальные 17 частей)

candidates = [A(80), B(45), C(30), D(70), E(60), F(20), G(90), H(50), I(25), ...]

Сортировка: G(90) → A(80) → D(70) → E(60) → H(50) → B(45) → ...

Выбор:
  G(90) — 70-115с   → берём
  A(80) — 5-50с     → не пересекается → берём
  D(70) — 32-77с    → пересекается с A → пропускаем
  E(60) — 40-85с    → пересекается с A → пропускаем
  H(50) — 75-120с   → пересекается с G → пропускаем
  B(45) — 10-55с    → пересекается с A → пропускаем
  ... → следующий непересекающийся → берём как 3й

Результат: [G(70-115с), A(5-50с), ...]
```

---

## Сравнительная таблица

| Режим | Скользящих окон | Вызовов `_find_best_segments` | Покрытие |
|-------|-----------------|-------------------------------|----------|
| off | 0 | 0 | Равномерное |
| parts | parts × (part_len / step) | parts + 1 (добивка) | Равномерное |
| global | duration / step | 1 (на все сегменты) | Только лучшие участки |
| hybrid | parts × (part_len / step) | parts (каждый даёт топ-3) + 1 сортировка | Хорошее |

---

## Вычислительная сложность (Big O)

### _build_phrases
- Проходит по списку сегментов **один раз**
- **O(M)**, где M — число Whisper-сегментов

### _find_best_segments (ядро)

```
N = duration / step        — количество окон (step = short_length // 2)
M = число Whisper-сегментов (фраз после _build_phrases)
```

1. **Скользящее окно + скоринг**: `O(N)` — каждое окно просматривает фразы.  
   В худшем случае каждая фраза в каждом окне: `O(N × M)` — если short_length = duration.

2. **Сортировка окон по score**: `O(N log N)`

3. **Отбор непересекающихся**: проход по отсортированным окнам: `O(N × K)`,  
   где K — число уже выбранных (макс shorts_count).  
   **Но** break при K = shorts_count, поэтому **`O(N)`** на практике.

4. **Добивка (второй проход)**: ещё `O(N × K)`, но тоже тривиально.

**Общая сложность одного вызова `_find_best_segments`:**  
**`O(N × M + N log N)`**, где:
- N = `duration / (short_length // 2)` — число окон
- M — число фраз (обычно M << N, так как фраз меньше, чем окон)

**Для `short_length = 45с`, видео 1 час (3600с):**
```
step = 45 // 2 = 22с
N = 3600 / 22 ≈ 163 окна
M ≈ 500–2000 фраз (зависит от речи)
```
→ 163 × 2000 = ~326 000 итераций — **ничтожно** для Python/SQLite.

### По режимам

| Режим | Вызовов | Сложность |
|-------|---------|-----------|
| **off** | 0 | O(1) |
| **parts** | `parts` раз × `_find_best_segments(part_len)` + 1 глобальный | `O(parts × (N_part × M_part + N_part log N_part) + N_global × M_global + N_global log N_global)` |
| **global** | 1 раз × `_find_best_segments(duration)` | `O(N × M + N log N)` |
| **hybrid** | `parts` раз × `_find_best_segments(part_len, top_k=3)` + сортировка кандидатов | `O(parts × (N_part × M_part + N_part log N_part) + C log C)`, где C = `parts × 3` — кандидатов |

**На практике для 1ч видео (3600с), short_length=45с, parts=200:**

```
part_len = 3600/200 = 18с
N_part = 18 / 22 ≈ 1 окно на часть (!)

parts:    200 × _find_best_segments(18с, 3) ≈ 200 × (1×M + 1×log1) = 200 × M
global:   1 × _find_best_segments(3600с, 2) ≈ 163 × M + 163 log 163
hybrid:   200 × _find_best_segments(18с, 3) + 600 log 600 ≈ 200 × M + небольшая сортировка
```

**Вывод:** все режимы работают за **линейное время** относительно длительности видео. Основное узкое место — **Whisper-транскрипция** (секунды на каждую часть), а не алгоритм отбора.
