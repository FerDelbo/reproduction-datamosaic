import React, { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  Box,
  Typography,
  CircularProgress
} from '@mui/material';
import {
  Save as SaveIcon,
  TableChart as TableChartIcon
} from '@mui/icons-material';

interface SaveTableDialogProps {
  open: boolean;
  onClose: () => void;
  tableData: string;
  projectId: string;
}

const SaveTableDialog: React.FC<SaveTableDialogProps> = ({
  open,
  onClose,
  tableData,
  projectId
}) => {
  const [tableName, setTableName] = useState('extracted_table');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSave = async () => {
    if (!tableName.trim()) {
      setError('Please enter a table name');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const lines = tableData.trim().split('\n');
      if (lines.length < 3) {
        throw new Error('Invalid table data format');
      }

      const headerLine = lines[0].replace(/^\||\|$/g, '').split('|').map(h => h.trim());
      
      const dataRows = [];
      for (let i = 2; i < lines.length; i++) {
        const row = lines[i].replace(/^\||\|$/g, '').split('|').map(cell => cell.trim());
        if (row.length === headerLine.length) {
          const rowObj: any = {};
          headerLine.forEach((header, index) => {
            rowObj[header] = row[index] || '';
          });
          dataRows.push(rowObj);
        }
      }

      if (dataRows.length === 0) {
        throw new Error('No valid data rows found');
      }

      let databaseId = '';
      
      const dbResponse = await fetch(`/api/projects/${projectId}/databases`);
      if (dbResponse.ok) {
        const dbData = await dbResponse.json();
        const databases = dbData.databases || [];
        
        const extractedDb = databases.find((db: any) => db.name === 'extracted_tables');
        if (extractedDb) {
          databaseId = extractedDb.id;
        }
      }

      if (!databaseId) {
        const createDbResponse = await fetch(`/api/projects/${projectId}/databases`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            name: 'extracted_tables',
            description: 'Table data extracted from documents'
          }),
        });

        if (!createDbResponse.ok) {
          const errorData = await createDbResponse.json().catch(() => ({}));
          throw new Error(errorData.error || 'Failed to create database');
        }

        const createDbData = await createDbResponse.json();
        databaseId = createDbData.database.id;
      }

      const saveResponse = await fetch(`/api/projects/${projectId}/databases/${databaseId}/tables`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          table_name: tableName,
          table_data: dataRows,
          merge_mode: 'create_new'
        }),
      });

      if (!saveResponse.ok) {
        const errorData = await saveResponse.json().catch(() => ({}));
        throw new Error(errorData.error || 'Failed to save table');
      }

      setSuccess(true);
      setTimeout(() => {
        onClose();
        setSuccess(false);
        setTableName('extracted_table');
        setDescription('');
      }, 1500);
    } catch (error) {
      setError('Save failed: ' + (error as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    if (!saving) {
      onClose();
      setError(null);
      setSuccess(false);
    }
  };

  return (
    <Dialog 
      open={open} 
      onClose={handleClose} 
      maxWidth="sm" 
      fullWidth
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <TableChartIcon />
        save table to database
      </DialogTitle>
      
      <DialogContent>
        {success ? (
          <Box sx={{ 
            display: 'flex', 
            flexDirection: 'column', 
            alignItems: 'center', 
            py: 3
          }}>
            <TableChartIcon sx={{ fontSize: 48, color: 'success.main', mb: 2 }} />
            <Typography variant="h6" color="success.main">
              table saved successfully!
            </Typography>
          </Box>
        ) : (
          <>
            <TextField
              fullWidth
              label="table name"
              value={tableName}
              onChange={(e) => setTableName(e.target.value)}
              margin="normal"
              required
              disabled={saving}
              helperText="please enter a meaningful table name"
            />
            
            <TextField
              fullWidth
              label="description (optional)"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              margin="normal"
              multiline
              rows={3}
              disabled={saving}
              helperText="describe the content and purpose of the table"
            />

            <Box sx={{ mt: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
              <Typography variant="body2" color="textSecondary">
                preview data rows: {tableData.split('\n').length - 2} rows
              </Typography>
            </Box>

            {error && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {error}
              </Alert>
            )}
          </>
        )}
      </DialogContent>
      
      <DialogActions>
        <Button 
          onClick={handleClose}
          disabled={saving}
        >
          cancel
        </Button>
        {!success && (
          <Button
            onClick={handleSave}
            variant="contained"
            disabled={saving || !tableName.trim()}
            startIcon={saving ? <CircularProgress size={20} /> : <SaveIcon />}
          >
            {saving ? 'saving...' : 'save'}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
};

export default SaveTableDialog;
