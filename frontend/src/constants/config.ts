/**
 * Application configuration constants
 */

export const PROJECT_ID = 'default-project';
export const PROJECT_NAME = 'Doc2DB';

export const SUPPORTED_MODELS = [
  'gpt-4o',
  'gpt-4o-mini',
  'o1',
  'deepseek-v3',
  'deepseek-r1',
  'claude-3-5-sonnet',
  'gemini-2.5-pro',
  'qwen-max',
  'qwen-long',
  'qwen-turbo',
] as const;

export type SupportedModel = typeof SUPPORTED_MODELS[number];

export interface FileItem {
  filename: string;
  filepath: string;
  size: number;
}
