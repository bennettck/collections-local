### Starting the Tool

1. **Launch the web server**:
   ```bash
   uvicorn main:app --reload
   ```

2. **Open the tool in browser**:
   ```
   http://localhost:8000/golden-dataset
   ```
   
# Golden Dataset Creation Tool

## Purpose

The Golden Dataset Creation Tool is a web-based interface for creating high-quality evaluation data to assess LLM analysis performance. By comparing multiple AI analyses of the same image, curators can identify the most accurate results and create a "golden" reference dataset for systematic quality measurement.

### Problem It Solves

When multiple LLM models analyze the same image, they often produce different results:
- Different extracted text from images
- Varying category classifications
- Different objects, themes, and emotions identified
- Alternative headlines and summaries

**Without this tool**: No systematic way to determine which analysis is most accurate or create ground truth data for evaluation.

**With this tool**: Curators can review all analyses side-by-side, see where models agree/disagree, and select or edit the best values to create a golden reference dataset.

## How It Works

### 1. Data Flow

```
┌─────────────────────────────────────────────────────────┐
│  Database: Items with Multiple LLM Analyses             │
│  - Item A: 3 analyses (Claude Sonnet, GPT-4o, Claude Opus)
│  - Item B: 7 analyses (various models/providers)        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Web UI: Golden Dataset Creator                         │
│  - Shows large image                                    │
│  - Displays all analyses side-by-side                   │
│  - Calculates similarity scores                         │
│  - Highlights where models agree/disagree               │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Curator Reviews & Selects Best Values                  │
│  - Pick best category, headline, summary                │
│  - Select correct objects/themes from merged lists      │
│  - Edit any field manually if needed                    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Golden Dataset (JSON File)                             │
│  data/eval/golden_analyses.json                         │
│  - One "correct" analysis per item                      │
│  - Used for evaluating future model performance         │
└─────────────────────────────────────────────────────────┘
```

### 2. Similarity Scoring

The tool automatically calculates how similar different analyses are:

**For Extracted Text** (text found in images):
- Uses **Levenshtein distance** (character-by-character comparison)
- Good for catching OCR-like differences, typos, spacing
- Example: "J-SCENT" vs "J-Scent" = 95% similar

**For Headlines & Summaries** (generated text):
- Uses **TF-IDF + Cosine Similarity** (semantic comparison)
- Good for understanding meaning across different wording
- Example: "Tokyo perfume shop" vs "Scent store in Tokyo" = 78% similar

**Visual Feedback**:
- 🟢 Green (90-100%): High agreement across models
- 🟡 Yellow (70-89%): Moderate agreement
- 🔴 Red (<70%): Low agreement, manual review needed

## Key Features

### Image & Analysis Display
- **Large image viewer**: Fixed-position image panel at 50% screen width with enlarged images (up to 900px height)
- **Sticky image panel**: Image remains visible while scrolling through attributes
- **Multi-analysis comparison**: View all model outputs simultaneously in tabbed sections
- **Model attribution**: Each analysis labeled with provider (Anthropic/OpenAI) and model version
- **Tabbed navigation**: Organized sections for Category, Extracted Text, Headline, Summary, Image Details, and Metadata
- **Section progress indicator**: Shows current section position (e.g., "Section 2 of 6")
- **Auto-scroll**: Automatically scrolls to top when navigating between sections

### Smart Comparison
- **Automatic similarity calculation**: System identifies which values have highest agreement
- **Recommended selections**: Highlights the most "agreed upon" value
- **Disagreement detection**: Alerts curator when models strongly disagree

### Flexible Editing
- **Select from analyses**: Pick the best value from any model's output
- **Manual override**: Edit any field directly if all models are wrong
- **Auto-select custom fields**: Clicking or typing in custom input fields automatically selects the corresponding radio button
- **Merge & filter**: For list fields (objects, themes), system shows union of all results; curator unchecks incorrect items
- **Drag-to-rank**: Visual hierarchy items can be reordered by dragging
- **Pre-populated review**: When reviewing existing golden records, form automatically loads with previously saved values

### Field Types

| Field | Selection Method | Similarity Method |
|-------|-----------------|-------------------|
| **Category** | Radio buttons (pick one) | N/A |
| **Subcategories** | Checkboxes (pick multiple) | N/A |
| **Extracted Text** | Radio + manual edit | Levenshtein |
| **Headline** | Radio + manual edit | TF-IDF |
| **Summary** | Radio + manual edit | TF-IDF |
| **Objects/Themes/Emotions** | Checkboxes (merged list) | N/A |
| **Key Interest** | Radio + manual edit | N/A |
| **Location Tags** | Checkboxes (merged list) | N/A |
| **Hashtags** | Checkboxes (merged list) | N/A |

### Progress Tracking & Review Modes
- **Review counter**: Shows how many items have golden data (e.g., "25 of 87 reviewed")
- **Progress bar**: Visual indicator of completion
- **Review mode selector**: Three viewing options:
  - **New Items Only** (default): Shows only items without golden records
  - **All Items**: Shows all items regardless of review status
  - **Reviewed Only**: Shows only items with existing golden records
- **Existing review indicator**: Yellow banner appears when viewing an item with a golden record, showing the previous review timestamp
- **Clear & Start Fresh**: Option to clear existing golden data and start a new review

### Data Safety & Session Management
- **Manual save**: Explicit save button with Ctrl+S keyboard shortcut
- **Save & Next**: Combined save and navigate action for efficient workflow
- **Atomic writes**: File corruption prevention with temporary file strategy
- **Session keepalive**: Prevents GitHub Codespace timeout during active use (30-minute inactivity timeout)
- **Review mode persistence**: Selected view mode (New/All/Reviewed) persists across page refreshes via localStorage

## How to Use

### Starting the Tool

1. **Launch the web server**:
   ```bash
   uvicorn main:app --reload
   ```

2. **Open the tool in browser**:
   ```
   http://localhost:8000/golden-dataset
   ```

3. **Tool loads first item automatically**

### Reviewing an Item

1. **View the image**: Large display shows what the AI analyzed

2. **Review similarity scores**: Look for green badges (high agreement) vs red badges (disagreement)

3. **Select best values**:
   - For category/headline/summary: Pick the radio button of the best analysis
   - For objects/themes/emotions: Uncheck any incorrect items from the merged list
   - For any field: Use manual edit if all AI outputs are wrong

4. **Save your work**:
   - Click "Save" to save current item
   - Click "Save & Next" to save and move to next item
   - Auto-save runs every 30 seconds

5. **Navigate**:
   - "Previous" button to go back to the previous item
   - "Next" button to move forward to the next item
   - Section navigation: "Previous Section" / "Next Section" buttons to move between attribute tabs
   - Review mode selector to switch between viewing unreviewed, all, or reviewed-only items

### Items with Single Analysis

For items with only one analysis (no comparison possible):
- Similarity scores are hidden (nothing to compare)
- Review the single analysis for accuracy
- Edit fields manually as needed
- Still create golden data for completeness

### Handling Edge Cases

**All models are wrong**: Use manual edit fields to enter correct values

**Models completely disagree** (all red scores): Carefully review the image and select/edit the most accurate option

**Empty fields**: Some analyses may not have certain fields - these will show as empty or "N/A"

**Very long lists**: If an item has many objects/themes (>20), consider focusing on the most important ones

## Output: Golden Dataset

### File Location
```
data/eval/golden_analyses.json
```

### Schema Structure

```json
{
  "metadata": {
    "version": "1.0",
    "last_updated": "2025-12-13T12:00:00Z",
    "total_items": 50
  },
  "golden_analyses": [
    {
      "item_id": "abc-123-def",
      "original_filename": "IMG_7901 Large.jpeg",
      "reviewed_at": "2025-12-13T10:30:00Z",
      "source_analyses_count": 3,
      "source_analysis_ids": ["analysis-id-1", "analysis-id-2", "analysis-id-3"],

      "category": "Beauty",
      "subcategories": ["Perfume", "Shopping"],
      "headline": "J-Scent perfume house in Tokyo offers affordable fragrances",
      "summary": "Visit to J-Scent perfume house in Tokyo. Purchased two scents...",

      "image_details": {
        "extracted_text": ["J-SCENT", "1500円"],
        "objects": ["perfume bottles", "tester bottles"],
        "themes": ["Japanese beauty", "perfume shopping"],
        "emotions": ["excited", "curious"],
        "vibes": ["luxurious", "intimate"],
        "visual_hierarchy": ["perfume bottles", "price tags", "brand name"],
        "key_interest": "Affordable luxury perfume discovery",
        "likely_source": "TikTok"
      },

      "media_metadata": {
        "location_tags": ["JAPAN", "Tokyo", "J-Scent"],
        "hashtags": ["#beauty", "#perfume", "#tokyo"],
        "tagged_accounts": [],
        "original_poster": "username",
        "audio_source": "original sound"
      }
    }
  ]
}
```

### Schema Design

**Key Feature**: The golden dataset matches the exact structure of the `raw_response` field from the analyses table. This makes downstream evaluation straightforward - you can directly compare a new analysis against the golden data field-by-field.

**Additional Metadata**:
- `item_id`: Unique identifier for the item in the database
- `original_filename`: Original filename of the uploaded image (e.g., "IMG_7901 Large.jpeg")
- `reviewed_at`: Timestamp of when curator reviewed this item
- `source_analyses_count`: How many analyses were compared
- `source_analysis_ids`: Which specific analyses were reviewed (for traceability)

## Use Cases for Golden Dataset

### 1. Model Performance Evaluation

Compare any model's analysis against golden data:

```python
# Evaluate a new model
new_analysis = analyze_image(image_path, model="claude-opus-4")
golden = load_golden_entry(item_id)

# Field-by-field comparison
category_match = new_analysis.category == golden.category
headline_similarity = calculate_tfidf(new_analysis.headline, golden.headline)
object_precision = len(set(new_analysis.objects) & set(golden.objects)) / len(new_analysis.objects)
```

### 2. Model Comparison

Which model is most accurate?

```python
# Compare multiple models against golden dataset
for model in ["claude-sonnet-4-5", "gpt-4o", "claude-opus-4"]:
    accuracy = evaluate_model_vs_golden(model, golden_dataset)
    print(f"{model}: {accuracy:.2%}")

# Output:
# claude-sonnet-4-5: 87.3%
# gpt-4o: 82.1%
# claude-opus-4: 91.2%
```

### 3. Regression Testing

Ensure model updates don't reduce quality:

```python
# Test new model version
old_accuracy = evaluate_model("claude-sonnet-4-5", golden_dataset)
new_accuracy = evaluate_model("claude-sonnet-5-0", golden_dataset)

if new_accuracy < old_accuracy:
    print("⚠️ Warning: New model performs worse!")
```

### 4. Field-Specific Analysis

Which fields are models best/worst at?

```python
# Per-field accuracy
results = {
    "category": 95%,
    "extracted_text": 88%,
    "objects": 76%,
    "emotions": 62%,
    "vibes": 54%
}

# Focus improvement efforts on low-scoring fields
```

## Technical Architecture

### Backend Components

**FastAPI Endpoints** (`main.py`):
- `GET /golden-dataset` - Serves the web UI
- `GET /golden-dataset/items` - Loads items with all analyses (supports `review_mode` parameter: unreviewed/all/reviewed)
- `GET /golden-dataset/entry/{item_id}` - Retrieves existing golden entry for an item
- `POST /golden-dataset/compare` - Calculates similarity scores
- `POST /golden-dataset/save` - Saves golden dataset entries (automatically includes `original_filename` from database)
- `GET /golden-dataset/status` - Returns progress statistics
- `POST /keepalive` - Session keepalive endpoint to prevent Codespace timeout

**Similarity Utilities** (`utils/similarity.py`):
- Levenshtein distance algorithm (character-level comparison)
- TF-IDF vectorization + cosine similarity (semantic comparison)
- Pairwise comparison matrix generation

**Golden Dataset I/O** (`utils/golden_dataset.py`):
- Load/save JSON with atomic writes (prevents corruption)
- Check review status for items
- Update metadata (last_updated, total_items)

### Frontend Components

**HTML** (`templates/golden_dataset.html`):
- Single-page application structure
- Sections for each field type
- Navigation and action buttons

**CSS** (`static/css/golden_dataset.css`):
- Card-based layout
- Color-coded similarity badges
- Responsive design

**JavaScript** (`static/js/golden_dataset.js`):
- Loads items from API
- Displays analyses and similarity scores
- Collects user selections
- Auto-save and navigation logic

### Data Flow

```
User Request → FastAPI → Database (fetch all analyses for item)
                      → Similarity Utils (calculate scores)
                      → Frontend (display with color coding)

User Edits → JavaScript (collect selections)
          → FastAPI (validate and save)
          → Golden Dataset JSON (append/update entry)
```

## Comparison with Existing Tools

### vs. Retrieval Test Set (`scripts/create_test_set.py`)

| Feature | Retrieval Test Set | Golden Dataset Tool |
|---------|-------------------|---------------------|
| **Purpose** | Evaluate search quality | Evaluate analysis quality |
| **Input** | Natural language queries | Images with multiple analyses |
| **Output** | Query → Item mappings | Item → Best analysis values |
| **Evaluation** | Retrieval metrics (precision, recall) | Field-level accuracy |
| **Use Case** | "Does search find the right items?" | "Are the analysis fields correct?" |

**Example**:
- **Retrieval**: Query "Tokyo restaurants" should return items [A, B, C]
- **Golden Dataset**: Item A's category should be "Food", not "Travel"

## Benefits

✅ **Systematic Quality Measurement**: Quantify how accurate each model is

✅ **Field-Level Granularity**: Understand which types of fields (category, objects, emotions) are hardest to analyze

✅ **Model Comparison**: Objectively compare different LLMs on the same task

✅ **Regression Prevention**: Catch quality degradation when updating models

✅ **Prompt Optimization**: Test prompt changes against golden dataset to measure improvement

✅ **Efficiency**: Review 182 items much faster with similarity highlighting and auto-save

✅ **Transparency**: Track which analyses contributed to golden data for debugging

## Future Enhancements

### Phase 2 Features (Not in Initial Implementation)

1. **Multi-Curator Support**: Multiple reviewers with conflict resolution
2. **Confidence Scoring**: Let curator rate confidence per field (high/medium/low)
3. **Bulk Actions**: Mark all high-similarity fields as correct with one click
4. **Export Formats**: CSV, SQL, or individual JSON files per item
5. **Comparison View**: Side-by-side diff of golden vs specific analysis
6. **Statistics Dashboard**: Overall agreement rates, model performance charts
7. **Search/Filter**: Find items by category, review status, number of analyses
8. **Undo/Redo**: Edit history within session

### Integration Possibilities

1. **Automated Evaluation Pipeline**: Run new analyses against golden dataset automatically
2. **CI/CD Integration**: Block deployments if model accuracy drops below threshold
3. **Annotation Guidelines**: Built-in reference guide for consistent curation
4. **Inter-Rater Reliability**: Measure agreement between multiple curators

## Getting Started

### Prerequisites
- Collections Local database with items and analyses
- Python environment with FastAPI, scikit-learn
- Modern web browser

### Setup Steps

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Start server:
   ```bash
   uvicorn main:app --reload
   ```

3. Open tool:
   ```
   http://localhost:8000/golden-dataset
   ```

4. Review items and create golden data

5. Export golden dataset:
   ```
   data/eval/golden_analyses.json
   ```

### Expected Time

- **Setup**: 5 minutes
- **Per item review**: 2-5 minutes (depending on complexity)
- **Full dataset (87 unique items)**: 3-7 hours of curator time

**Recommendation**: Review 10-20 items per session to avoid fatigue. Use "New Items Only" mode to focus on unreviewed items. The tool will maintain your session active for up to 30 minutes of inactivity.

### Database Cleanup

The database has been cleaned to remove duplicate items (items with the same `original_filename`):
- **Before cleanup**: 182 items (with duplicates)
- **After cleanup**: 87 unique items
- **Duplicate handling**: Kept items with golden records (most recently reviewed), or oldest item if no golden records exist

## Questions?

For implementation details, see the technical plan at:
```
/home/codespace/.claude/plans/serene-frolicking-flame.md
```

For usage during evaluation, refer to this document.
