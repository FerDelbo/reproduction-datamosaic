# MCP Configuration Files

This directory contains configuration files for MCP (Model Context Protocol) modules, used to define data quality constraint rules and repair strategies.

## Configuration File List

### 1. format_rules.json
Format constraint rules configuration file

**Configuration contents:**
- Field format rule definitions
- Standard format patterns (regular expressions)
- Format conversion mapping tables
- Standard example values

**Supported fields:**
- `季度` (quarter): Chinese quarter format (e.g., 第一季度, 第二季度)
- `税额` (tax amount): Amount format (in 100 million yuan)

**Use cases:**
- Format validation: check whether field values match the standard format
- Format repair: convert non-standard formats to standard formats
- Batch normalization: ensure a field uses a unified format within a table

### 2. aggregation_rules.json
Aggregation constraint rules configuration file

**Configuration contents:**
- Aggregation keyword definitions (total, average, etc.)
- Calculation type configuration (sum, multiplication, percentage, etc.)
- Field repair rules
- Tolerance settings

**Supported repair types:**
- `amount_unit`: unify amount units
- `quarter_format`: unify quarter formats

**Use cases:**
- Aggregation validation: check correctness of totals, averages, and other aggregate calculations
- Unit normalization: ensure similar data uses the same unit
- Format consistency: keep aggregate data formats consistent

## Configuration File Structure

### format_rules.json structure
```json
{
  "field_format_rules": {
    "field_name": {
      "pattern": "regular_expression",
      "standard_examples": ["example1", "example2"],
      "description": "rule description",
      "mapping": {
        "variant1": "standard_format",
        "variant2": "standard_format"
      },
      "conversion_rules": [
        {
          "pattern": "match_pattern",
          "template": "conversion_template",
          "description": "conversion description"
        }
      ]
    }
  }
}
```

### aggregation_rules.json structure
```json
{
  "aggregation_keywords": {
    "total": ["keyword_list"],
    "average": ["keyword_list"]
  },
  "calculation_types": {
    "type_name": {
      "description": "description",
      "tolerance": tolerance_value
    }
  },
  "field_fix_rules": {
    "field_name": {
      "type": "repair_type",
      "target_format": "target_format",
      "mapping": {},
      "conversion_rules": []
    }
  }
}
```

## How to Add New Rules

### Add a new format rule

1. Add a new field under `field_format_rules` in `format_rules.json`:
```json
"new_field_name": {
  "pattern": "^regular_expression$",
  "standard_examples": ["example"],
  "description": "rule description",
  "mapping": {
    "variant": "standard_format"
  }
}
```

2. Add the corresponding handler in `FormatFixer.__init__()` in `format_mcp.py`:
```python
if field_name == 'new_field_name':
    self.format_normalizers[field_name] = self._normalize_new_field
```

3. Implement the normalization method:
```python
def _normalize_new_field(self, value: str) -> Optional[str]:
    # Implement conversion logic
    pass
```

### Add a new aggregation rule

1. Add a new field repair rule in `aggregation_rules.json`
2. Add the corresponding handler in `AggregationFixer`
3. Add the new repair type check in `_generate_aggregation_fix`

## Best Practices

1. **Configuration first**: define all rules in JSON configuration files whenever possible; avoid hardcoding
2. **Unified format**: use a consistent standard format for fields of the same type
3. **Progressive enhancement**: keep backward compatibility when adding new rules
4. **Keep docs in sync**: update this document when configuration changes

## Notes

- Special characters in regular expressions must be escaped (use `\\` instead of `\`)
- Mapping table keys should be lowercase (the program converts to lowercase for matching)
- Tolerance values are used for floating-point comparisons to avoid precision issues
- Configuration files must be valid JSON; avoid trailing commas
