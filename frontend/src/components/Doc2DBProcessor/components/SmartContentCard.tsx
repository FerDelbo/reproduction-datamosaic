import React from 'react';
import {
  Box,
  Typography,
  IconButton,
  Chip,
  Collapse
} from '@mui/material';
import {
  CheckCircle as CheckCircleIcon,
  Code as CodeIcon
} from '@mui/icons-material';
import { containsTable, extractTableContent, splitContentWithTables, splitContentForDocumentInput } from '../utils/processingUtils';
import LargeContentViewer from '../../LargeContentViewer';

interface SmartContentCardProps {
  title: string;
  content: string;
  type: 'input' | 'output' | 'prompt' | 'result';
  maxHeight?: string;
  projectId?: string;
  isDocumentInput?: boolean;
}

const SmartContentCard: React.FC<SmartContentCardProps> = ({ 
  title, 
  content, 
  type, 
  maxHeight = '300px',
  projectId,
  isDocumentInput = false
}) => {
  const [collapsed, setCollapsed] = React.useState(type === 'prompt' || type === 'input');
  const [copying, setCopying] = React.useState(false);
  
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopying(true);
      setTimeout(() => setCopying(false), 2000);
    } catch (error) {
      console.error('Copy failed:', error);
    }
  };

  const getCardStyle = () => {
    return {
      bgcolor: '#f8fafc',
      borderColor: '#e2e8f0',
      iconColor: '#6b7280',
      icon: type === 'input' ? '📥' : 
            type === 'output' ? '📤' :
            type === 'prompt' ? '⚙️' :
            type === 'result' ? '✅' : '📄'
    };
  };

  const style = getCardStyle();
  const isLongContent = content.length > 500;

  return (
    <Box sx={{ mb: 2 }}>
      <Box sx={{ 
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        mb: 1,
        cursor: isLongContent ? 'pointer' : 'default'
      }}
      onClick={isLongContent ? () => setCollapsed(!collapsed) : undefined}
      >
        <Typography variant="subtitle2" sx={{ 
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          color: style.iconColor,
          fontSize: '0.875rem'
        }}>
          <span style={{ fontSize: '0.875rem' }}>{style.icon}</span>
          {title}
          {isLongContent && (
            <Chip 
              size="small" 
              label={collapsed ? 'open' : 'close'}
              sx={{ fontSize: '0.6rem', height: '16px', ml: 1 }}
            />
          )}
        </Typography>
            
        <Box sx={{ display: 'flex', gap: 1 }}>
          <IconButton
            size="small" 
            onClick={(e) => {
              e.stopPropagation();
              handleCopy();
            }}
            sx={{ width: 24, height: 24 }}
          >
            {copying ? (
              <CheckCircleIcon sx={{ fontSize: '14px', color: 'success.main' }} />
            ) : (
              <CodeIcon sx={{ fontSize: '14px', color: 'text.secondary' }} />
            )}
          </IconButton>
        </Box>
      </Box>

      <Collapse in={!collapsed || !isLongContent}>
        <Box sx={{ 
          p: 2, 
          bgcolor: style.bgcolor,
          border: `1px solid ${style.borderColor}`,
          borderRadius: 1.5,
          maxHeight: maxHeight,
          overflow: 'auto',
          position: 'relative'
        }}>
          {(isDocumentInput ? splitContentForDocumentInput(content) : splitContentWithTables(content)).map((part, index) => (
            part.type === 'table' ? (
              <LargeContentViewer
                key={`table-${index}`}
                content={part.content}
                contentType="table"
                preview={part.content}
                projectId={projectId}
              />
            ) : (
              <pre 
                key={`text-${index}`}
                style={{ 
                  margin: index === 0 ? 0 : '16px 0 0 0', 
                  whiteSpace: 'pre-wrap', 
                  fontSize: '0.8rem',
                  fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", monospace',
                  color: '#374151',
                  lineHeight: 1.5
                }}
              >
                {part.content}
              </pre>
            )
          ))}
        </Box>
      </Collapse>
    </Box>
  );
};

export default SmartContentCard;



