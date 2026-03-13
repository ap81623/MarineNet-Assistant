const STORAGE_KEY = 'personal-kanban-board-v1';
const THEME_KEY = 'personal-kanban-theme';

const memoryStorage = {};

function storageGet(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    return Object.prototype.hasOwnProperty.call(memoryStorage, key)
      ? memoryStorage[key]
      : null;
  }
}

function storageSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    memoryStorage[key] = String(value);
  }
}

function generateId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  if (globalThis.crypto?.getRandomValues) {
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0'));
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex
      .slice(6, 8)
      .join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`;
  }
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createDefaultBoard() {
  return {
    name: 'Personal Tasks',
    columns: [
      { id: generateId(), title: 'To Do', taskIds: [] },
      { id: generateId(), title: 'Doing', taskIds: [] },
      { id: generateId(), title: 'Done', taskIds: [] },
    ],
    tasks: {},
  };
}

let board = null;
let dragState = {
  taskId: null,
  sourceColumnId: null,
  columnId: null,
};

let boardEl = null;
let searchInput = null;
let boardNameInput = null;
let newColumnInput = null;
let addColumnBtn = null;
let taskTitleInput = null;
let taskDescInput = null;
let taskDueInput = null;
let taskPriorityInput = null;
let taskColumnSelect = null;
let addTaskBtn = null;
let importBoardBtn = null;
let exportBoardBtn = null;
let importBoardInput = null;
let resetBoardBtn = null;
let themeToggleBtn = null;
let columnTemplate = null;
let taskTemplate = null;

function hydrateElements() {
  boardEl = document.getElementById('board');
  searchInput = document.getElementById('search-input');
  boardNameInput = document.getElementById('board-name-input');
  newColumnInput = document.getElementById('new-column-title');
  addColumnBtn = document.getElementById('add-column-btn');
  taskTitleInput = document.getElementById('task-title-input');
  taskDescInput = document.getElementById('task-desc-input');
  taskDueInput = document.getElementById('task-due-input');
  taskPriorityInput = document.getElementById('task-priority-input');
  taskColumnSelect = document.getElementById('task-column-select');
  addTaskBtn = document.getElementById('add-task-btn');
  importBoardBtn = document.getElementById('import-board-btn');
  exportBoardBtn = document.getElementById('export-board-btn');
  importBoardInput = document.getElementById('import-board-input');
  resetBoardBtn = document.getElementById('reset-board-btn');
  themeToggleBtn = document.getElementById('theme-toggle');
  columnTemplate = document.getElementById('column-template');
  taskTemplate = document.getElementById('task-template');
}

function loadTheme() {
  const stored = storageGet(THEME_KEY);
  const prefersDark =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme = stored || (prefersDark ? 'dark' : 'light');
  document.documentElement.dataset.theme = theme === 'dark' ? '' : 'light';
  updateThemeToggleIcon();
}

function toggleTheme() {
  const isLight = document.documentElement.dataset.theme === 'light';
  document.documentElement.dataset.theme = isLight ? '' : 'light';
  storageSet(THEME_KEY, isLight ? 'dark' : 'light');
  updateThemeToggleIcon();
}

function updateThemeToggleIcon() {
  const isLight = document.documentElement.dataset.theme === 'light';
  themeToggleBtn.textContent = isLight ? '🌙' : '☀️';
}

function loadBoard() {
  try {
    const raw = storageGet(STORAGE_KEY);
    if (!raw) throw new Error('no board');
    const parsed = JSON.parse(raw);
    const sanitized = sanitizeBoard(parsed);
    if (!sanitized) throw new Error('invalid board');
    board = sanitized;
  } catch (e) {
    board = createDefaultBoard();
    persistBoard();
  }
}

function isValidDateString(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }
  const parsed = new Date(value + 'T00:00:00');
  return !Number.isNaN(parsed.getTime());
}

function sanitizeBoard(input) {
  if (!input || typeof input !== 'object') return null;
  if (!input.tasks || typeof input.tasks !== 'object') return null;

  const tasks = {};
  Object.values(input.tasks).forEach((task) => {
    if (!task || typeof task !== 'object') return;
    const id = typeof task.id === 'string' ? task.id : null;
    const title = typeof task.title === 'string' ? task.title.trim() : '';
    if (!id || !title) return;
    tasks[id] = {
      id,
      title,
      description:
        typeof task.description === 'string' ? task.description.trim() : '',
      dueDate: isValidDateString(task.dueDate) ? task.dueDate : '',
      priority:
        task.priority === 'low' || task.priority === 'high'
          ? task.priority
          : 'medium',
      createdAt:
        typeof task.createdAt === 'string'
          ? task.createdAt
          : new Date().toISOString(),
    };
  });

  const rawColumns = Array.isArray(input.columns) ? input.columns : [];
  const seenColumnIds = new Set();
  const columns = rawColumns
    .map((column) => {
      if (!column || typeof column !== 'object') return null;
      const title =
        typeof column.title === 'string' && column.title.trim()
          ? column.title.trim()
          : 'Untitled';
      let id =
        typeof column.id === 'string' && column.id
          ? column.id
          : generateId();
      if (seenColumnIds.has(id)) {
        id = generateId();
      }
      seenColumnIds.add(id);
      const taskIds = Array.isArray(column.taskIds)
        ? column.taskIds.filter((taskId) => typeof taskId === 'string')
        : [];
      return { id, title, taskIds };
    })
    .filter(Boolean);

  if (columns.length === 0) {
    const fallback = createDefaultBoard();
    fallback.tasks = tasks;
    if (Object.keys(tasks).length > 0) {
      fallback.columns[0].taskIds = Object.keys(tasks);
    }
    return fallback;
  }

  const assigned = new Set();
  columns.forEach((column) => {
    column.taskIds = column.taskIds.filter((taskId) => {
      if (!tasks[taskId] || assigned.has(taskId)) return false;
      assigned.add(taskId);
      return true;
    });
  });

  Object.keys(tasks).forEach((taskId) => {
    if (!assigned.has(taskId)) {
      columns[0].taskIds.push(taskId);
    }
  });

  return {
    name:
      typeof input.name === 'string' && input.name.trim()
        ? input.name.trim()
        : 'Personal Tasks',
    columns,
    tasks,
  };
}

function persistBoard() {
  storageSet(STORAGE_KEY, JSON.stringify(board));
}

function createTask({ title, description, dueDate, priority, columnId }) {
  const column = board.columns.find((c) => c.id === columnId);
  if (!column) return;
  const id = generateId();
  board.tasks[id] = {
    id,
    title,
    description,
    dueDate,
    priority,
    createdAt: new Date().toISOString(),
  };
  column.taskIds.unshift(id);
  persistBoard();
  renderBoard();
}

function updateTask(id, updates) {
  if (!board.tasks[id]) return;
  board.tasks[id] = { ...board.tasks[id], ...updates };
  persistBoard();
  renderBoard();
}

function deleteTask(id) {
  delete board.tasks[id];
  board.columns.forEach((c) => {
    c.taskIds = c.taskIds.filter((tid) => tid !== id);
  });
  persistBoard();
  renderBoard();
}

function createColumn(title) {
  const id = generateId();
  const column = { id, title, taskIds: [] };
  board.columns.push(column);
  persistBoard();
  renderBoard();
}

function renameColumn(id, title) {
  const col = board.columns.find((c) => c.id === id);
  if (!col) return;
  col.title = title;
  persistBoard();
  renderBoard();
}

function deleteColumn(id) {
  if (board.columns.length <= 1) {
    alert('You need at least one column on the board.');
    return;
  }
  const col = board.columns.find((c) => c.id === id);
  if (!col) return;
  col.taskIds.forEach((taskId) => {
    delete board.tasks[taskId];
  });
  board.columns = board.columns.filter((c) => c.id !== id);
  persistBoard();
  renderBoard();
}

function moveTask(taskId, targetColumnId, targetIndex) {
  if (!board.tasks[taskId]) return;
  let sourceColumn = null;
  board.columns.forEach((c) => {
    if (c.taskIds.includes(taskId)) {
      sourceColumn = c;
      c.taskIds = c.taskIds.filter((tid) => tid !== taskId);
    }
  });
  const targetColumn = board.columns.find((c) => c.id === targetColumnId);
  if (!targetColumn) {
    if (sourceColumn && !sourceColumn.taskIds.includes(taskId)) {
      sourceColumn.taskIds.push(taskId);
    }
    return;
  }
  const index = targetIndex ?? targetColumn.taskIds.length;
  targetColumn.taskIds.splice(index, 0, taskId);
  persistBoard();
  renderBoard();
}

function saveBoardName(name) {
  board.name = name;
  persistBoard();
}

function resetBoard() {
  if (!confirm('Reset board? All tasks will be permanently removed.')) return;
  board = createDefaultBoard();
  persistBoard();
  renderBoard();
}

function exportBoard() {
  const json = JSON.stringify(board, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const stamp = new Date().toISOString().slice(0, 10);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `personal-kanban-backup-${stamp}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function importBoard(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const parsed = JSON.parse(String(reader.result));
      const sanitized = sanitizeBoard(parsed);
      if (!sanitized) throw new Error('invalid');
      board = sanitized;
      persistBoard();
      renderBoard();
      alert('Board imported successfully.');
    } catch (error) {
      alert('Could not import this file. Please use a valid board backup JSON.');
    } finally {
      importBoardInput.value = '';
    }
  };
  reader.onerror = () => {
    alert('Could not read the selected file.');
    importBoardInput.value = '';
  };
  reader.readAsText(file);
}

function formatDueDate(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr + 'T00:00:00');
  if (Number.isNaN(date.getTime())) return '';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.floor((date - today) / (1000 * 60 * 60 * 24));
  if (diff === 0) return 'Due today';
  if (diff === 1) return 'Due tomorrow';
  if (diff === -1) return 'Due yesterday';
  if (diff > 1) return `Due in ${diff} days`;
  return `${Math.abs(diff)} days overdue`;
}

function isOverdue(dateStr) {
  if (!dateStr) return false;
  const date = new Date(dateStr + 'T23:59:59');
  return date.getTime() < Date.now();
}

function renderBoard() {
  boardEl.innerHTML = '';
  taskColumnSelect.innerHTML = '';

  boardNameInput.value = board.name || '';

  const optionFragment = document.createDocumentFragment();
  board.columns.forEach((column) => {
    const option = document.createElement('option');
    option.value = column.id;
    option.textContent = column.title;
    optionFragment.appendChild(option);
  });
  taskColumnSelect.appendChild(optionFragment);

  const searchTerm = searchInput.value.trim().toLowerCase();

  board.columns.forEach((column) => {
    const columnNode = columnTemplate.content.firstElementChild.cloneNode(true);
    columnNode.dataset.columnId = column.id;

    const titleEl = columnNode.querySelector('.column-title');
    const dropzone = columnNode.querySelector('.column-dropzone');
    const editBtn = columnNode.querySelector('.column-edit-btn');
    const deleteBtn = columnNode.querySelector('.column-delete-btn');
    const quickAddBtn = columnNode.querySelector('.column-add-task-btn');

    titleEl.textContent = column.title;

    const visibleTaskIds = [];
    column.taskIds.forEach((taskId) => {
      const task = board.tasks[taskId];
      if (!task) return;

      const matchesSearch =
        !searchTerm ||
        task.title.toLowerCase().includes(searchTerm) ||
        (task.description || '').toLowerCase().includes(searchTerm);

      if (!matchesSearch) return;
      visibleTaskIds.push(taskId);

      const taskNode = taskTemplate.content.firstElementChild.cloneNode(true);
      taskNode.dataset.taskId = task.id;

      const titleSpan = taskNode.querySelector('.task-title');
      const descP = taskNode.querySelector('.task-desc');
      const dueSpan = taskNode.querySelector('.task-due');
      const priorityPill = taskNode.querySelector('.task-priority-pill');
      const editTaskBtn = taskNode.querySelector('.task-edit-btn');
      const deleteTaskBtn = taskNode.querySelector('.task-delete-btn');

      titleSpan.textContent = task.title;
      descP.textContent = task.description || '';
      if (!task.description) {
        descP.style.display = 'none';
      } else {
        descP.style.display = '-webkit-box';
        descP.style.webkitLineClamp = '3';
        descP.style.webkitBoxOrient = 'vertical';
      }

      const formattedDue = formatDueDate(task.dueDate);
      dueSpan.textContent = formattedDue;

      priorityPill.dataset.priority = task.priority || 'medium';
      priorityPill.textContent =
        task.priority === 'high'
          ? 'High'
          : task.priority === 'low'
          ? 'Low'
          : 'Medium';

      if (isOverdue(task.dueDate)) {
        taskNode.classList.add('overdue');
      }

      taskNode.addEventListener('dragstart', (e) => {
        dragState.taskId = task.id;
        dragState.sourceColumnId = column.id;
        taskNode.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
      });

      taskNode.addEventListener('dragend', () => {
        dragState.taskId = null;
        dragState.sourceColumnId = null;
        taskNode.classList.remove('dragging');
      });

      editTaskBtn.addEventListener('click', () => {
        const updatedTitle = prompt('Task title', task.title);
        if (!updatedTitle) return;
        const updatedDesc = prompt(
          'Task description (leave blank to clear)',
          task.description || ''
        );
        const updatedDue = prompt(
          'Due date (YYYY-MM-DD, leave blank for none)',
          task.dueDate || ''
        );
        const updatedPriority = prompt(
          'Priority (low, medium, high)',
          task.priority || 'medium'
        );
        updateTask(task.id, {
          title: updatedTitle,
          description: updatedDesc || '',
          dueDate: updatedDue || '',
          priority:
            updatedPriority === 'low' || updatedPriority === 'high'
              ? updatedPriority
              : 'medium',
        });
      });

      deleteTaskBtn.addEventListener('click', () => {
        if (!confirm('Delete this task?')) return;
        deleteTask(task.id);
      });

      dropzone.appendChild(taskNode);
    });

    titleEl.setAttribute('data-count', visibleTaskIds.length);

    columnNode.addEventListener('dragstart', (e) => {
      if (e.target !== columnNode) return;
      columnNode.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/column', column.id);
    });

    columnNode.addEventListener('dragend', () => {
      columnNode.classList.remove('dragging');
    });

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('drag-over');
      e.dataTransfer.dropEffect = 'move';
    });

    dropzone.addEventListener('dragleave', (e) => {
      if (!dropzone.contains(e.relatedTarget)) {
        dropzone.classList.remove('drag-over');
      }
    });

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('drag-over');
      const columnId = column.id;

      const draggedColumnId = e.dataTransfer.getData('text/column');
      if (draggedColumnId) {
        const fromIndex = board.columns.findIndex(
          (c) => c.id === draggedColumnId
        );
        const toIndex = board.columns.findIndex((c) => c.id === column.id);
        if (fromIndex === -1 || toIndex === -1) return;
        const [moved] = board.columns.splice(fromIndex, 1);
        board.columns.splice(toIndex, 0, moved);
        persistBoard();
        renderBoard();
        return;
      }

      const draggingTaskId = dragState.taskId;
      if (!draggingTaskId) return;

      const afterElement = getDragAfterElement(dropzone, e.clientY);
      const targetIndex = afterElement
        ? Array.from(dropzone.children).indexOf(afterElement)
        : dropzone.children.length;
      moveTask(draggingTaskId, columnId, targetIndex);
    });

    editBtn.addEventListener('click', () => {
      const newTitle = prompt('Column title', column.title);
      if (!newTitle) return;
      renameColumn(column.id, newTitle.trim());
    });

    deleteBtn.addEventListener('click', () => {
      if (!confirm('Delete this column and all its tasks?')) return;
      deleteColumn(column.id);
    });

    quickAddBtn.addEventListener('click', () => {
      const title = prompt('Task title');
      if (!title) return;
      createTask({
        title: title.trim(),
        description: '',
        dueDate: '',
        priority: 'medium',
        columnId: column.id,
      });
    });

    boardEl.appendChild(columnNode);
  });
}

function getDragAfterElement(container, y) {
  const draggableElements = [
    ...container.querySelectorAll('.task-card:not(.dragging)'),
  ];

  return draggableElements.reduce(
    (closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) {
        return { offset, element: child };
      }
      return closest;
    },
    { offset: Number.NEGATIVE_INFINITY, element: null }
  ).element;
}

function bindEvents() {
  searchInput.addEventListener('input', () => {
    renderBoard();
  });

  boardNameInput.addEventListener('change', () => {
    const value = boardNameInput.value.trim();
    saveBoardName(value || 'Personal Tasks');
  });

  addColumnBtn.addEventListener('click', () => {
    const title = newColumnInput.value.trim();
    if (!title) return;
    createColumn(title);
    newColumnInput.value = '';
  });

  newColumnInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addColumnBtn.click();
    }
  });

  addTaskBtn.addEventListener('click', () => {
    const title = taskTitleInput.value.trim();
    if (!title) return;
    const columnId = taskColumnSelect.value || board.columns[0]?.id;
    createTask({
      title,
      description: taskDescInput.value.trim(),
      dueDate: taskDueInput.value,
      priority: taskPriorityInput.value,
      columnId,
    });
    taskTitleInput.value = '';
    taskDescInput.value = '';
    taskDueInput.value = '';
    taskPriorityInput.value = 'medium';
  });

  taskTitleInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      addTaskBtn.click();
    }
  });

  importBoardBtn.addEventListener('click', () => {
    importBoardInput.click();
  });
  importBoardInput.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    importBoard(file);
  });
  exportBoardBtn.addEventListener('click', exportBoard);
  resetBoardBtn.addEventListener('click', resetBoard);
  themeToggleBtn.addEventListener('click', toggleTheme);
}

function hasRequiredElements() {
  return [
    boardEl,
    searchInput,
    boardNameInput,
    newColumnInput,
    addColumnBtn,
    taskTitleInput,
    taskDescInput,
    taskDueInput,
    taskPriorityInput,
    taskColumnSelect,
    addTaskBtn,
    importBoardBtn,
    exportBoardBtn,
    importBoardInput,
    resetBoardBtn,
    themeToggleBtn,
    columnTemplate,
    taskTemplate,
  ].every(Boolean);
}

function init() {
  hydrateElements();
  if (!hasRequiredElements()) {
    console.error('Kanban app failed to initialize: missing required DOM nodes.');
    return;
  }
  try {
    loadTheme();
    loadBoard();
    bindEvents();
    renderBoard();
  } catch (error) {
    console.error('Kanban app failed to initialize.', error);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
