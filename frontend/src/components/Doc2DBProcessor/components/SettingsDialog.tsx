import React from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  TextField,
  FormControl,
  Select,
  MenuItem,
  Chip
} from '@mui/material';
import {
  Settings as SettingsIcon
} from '@mui/icons-material';
import { MODEL_OPTIONS } from '../constants';
import { normalizeModelValue } from '../utils/processingUtils';

interface SettingsDialogProps {
  open: boolean;
  onClose: () => void;
  currentModel: string;
  apiKey: string;
  apiUrl: string;
  isSaving: boolean;
  saveMessage: string;
  setCurrentModel: (model: string) => void;
  setApiKey: (key: string) => void;
  setApiUrl: (url: string) => void;
  onSave: () => void;
}

const SettingsDialog: React.FC<SettingsDialogProps> = ({
  open,
  onClose,
  currentModel,
  apiKey,
  apiUrl,
  isSaving,
  saveMessage,
  setCurrentModel,
  setApiKey,
  setApiUrl,
  onSave
}) => {
  return (
    <Dialog 
      open={open} 
      onClose={onClose} 
      maxWidth="sm" 
      fullWidth
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <SettingsIcon />
        Model Settings
      </DialogTitle>
      <DialogContent dividers>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3, py: 2 }}>
          <Box>
            <Typography variant="h6" sx={{ mb: 2, fontSize: '1rem', fontWeight: 600 }}>
              Model Settings
            </Typography>
            
            <FormControl fullWidth sx={{ mb: 2 }}>
              <Typography variant="body2" sx={{ mb: 1, fontWeight: 500 }}>Model</Typography>
              <Select
                value={normalizeModelValue(currentModel)}
                onChange={(e) => setCurrentModel(e.target.value)}
                size="small"
              >
                {MODEL_OPTIONS.filter(model => model.value !== 'settings').map((model) => (
                  <MenuItem key={model.value} value={model.value}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="body2">
                        {model.label}
                      </Typography>
                      <Chip
                        label={model.category.toUpperCase()}
                        size="small"
                        sx={{
                          height: '16px',
                          fontSize: '0.625rem',
                          backgroundColor: 
                            model.category === 'gpt' ? '#dbeafe' :
                            model.category === 'deepseek' ? '#dcfce7' :
                            model.category === 'claude' ? '#fef3c7' :
                            model.category === 'gemini' ? '#fce7f3' :
                            model.category === 'qianwen' ? '#f3e8ff' : '#f1f5f9',
                          color:
                            model.category === 'gpt' ? '#1d4ed8' :
                            model.category === 'deepseek' ? '#166534' :
                            model.category === 'claude' ? '#92400e' :
                            model.category === 'gemini' ? '#9f1239' :
                            model.category === 'qianwen' ? '#7c3aed' : '#475569',
                        }}
                      />
                    </Box>
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <TextField
              fullWidth
              label="API Key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Input API Key"
              size="small"
              sx={{ mb: 2 }}
            />

            <TextField
              fullWidth
              label="API URL"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="Input API URL"
              size="small"
            />
          </Box>
        </Box>
      </DialogContent>
      <DialogActions>
        {saveMessage && (
          <Typography variant="body2" sx={{ 
            color: saveMessage.includes('failed') || saveMessage.includes('Failed') ? 'error.main' : 'success.main', 
            mr: 2 
          }}>
            {saveMessage}
          </Typography>
        )}
        <Button onClick={onClose}>
          Cancel
        </Button>
        <Button 
          onClick={onSave} 
          variant="contained"
          disabled={isSaving}
        >
          {isSaving ? 'Saving...' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default SettingsDialog;



