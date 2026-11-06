# 🇪🇸 Antigravity Spanish Tutor

An adaptive, in-IDE Spanish tutoring environment local to this project, built on commercial language learning principles (Task-Based Language Teaching + SuperMemo SM-2 Spaced Retrieval).

---

## 🌟 Key Features

1. **Commercial Pedagogy (Babbel / Duolingo methodology)**:
   - Learn via real-world communicative missions (ordering food, booking trains, casual introductions).
   - Long-term memory retention powered by the SuperMemo SM-2 Spaced Repetition Algorithm.
2. **English-First Instructional Ladder**:
   - Zero intimidation: All mission parameters, scenarios, and grammar explanations are provided in English before prompting your Spanish output.
3. **Local SQLite Persistence**:
   - Your progress, vocabulary mastery, CEFR level, and review schedules are stored locally in `.tutor/state.db`.
4. **Agent Ecosystem**:
   - **Spanish Tutor (`spanish-tutor`)**: Learner-facing bilingual companion and dialogue partner.
   - **Developer / Maintainer Agent (`developer-tutor`)**: Engineering sub-agent responsible for codebase maintenance, feature rollouts, schema migrations, and TDD.
   - **QA & Issue Triage Agent (`qa-tutor`)**: Quality assurance sub-agent specialized in issue triage, bug reproduction in isolated test databases, and regression suites.

---

## 🚀 Getting Started

Simply message your tutor in chat:
> *"Hello! Let's start our Spanish lesson."*

If this is your first time, the tutor will automatically launch the **3-Question Adaptive Diagnostic** to establish your starting CEFR level (A1, A2, B1, B2).

---

## 🛠️ CLI Utilities & Session Commands (`tutor_db.py`)

You can inspect or manage your progress at any time directly in the terminal or use in-chat textual cues:

```bash
# View complete session summary (level, XP, settings, review count)
python3 tutor_db.py get-session-summary

# View active settings
python3 tutor_db.py get-settings

# Update settings directly (feedback_style, language_ratio, current_mode, cefr_level)
python3 tutor_db.py set-setting feedback_style strict
python3 tutor_db.py set-setting current_mode drill
python3 tutor_db.py set-setting cefr_level B1

# Batch sync reviews, new vocabulary, settings, and missions atomically (low-latency orchestration)
python3 tutor_db.py batch-sync '{"new_vocab":[{"spanish":"la toalla","english":"the towel","category":"hotel"}],"reviews":[{"spanish":"la toalla","quality_score":5}],"xp":25,"mission":{"title":"Hotel Service","cefr_level":"A2","scenario_description":"Request towels","score":95}}'

# View vocabulary due for review
python3 tutor_db.py get-due-vocab

# Add new vocabulary
python3 tutor_db.py add-vocab "la cuenta" "the bill" "dining"

# Run tests
python3 -m unittest discover -s tests
```

### In-Chat Textual Cues & Commands
During conversation with the tutor, you can quickly adjust modes and preferences using quick commands or natural language:
- `!mode <diagnostic|mission|drill|free_chat>`
- `!feedback <gentle|balanced|strict>`
- `!level <A1|A2|B1|B2|C1>`
- `!ratio <en_first|bilingual|immersion>`
- `!refresh` (Force synchronization with database)
- Or ask naturally: *"Can you be stricter on grammar?"*, *"Let's switch to a quick drill"*.

### Anti-Hallucination Best Practices
- **Mid-Session Compaction**: Run `/compact` after 15–20 turns to compress transcript history.
- **Fresh Chats**: Starting a new chat carries **zero loss of progress** because your entire profile and spaced repetition intervals are stored in `.tutor/state.db`. The tutor immediately rehydrates from the database on Turn 1 with zero hallucination risk.
