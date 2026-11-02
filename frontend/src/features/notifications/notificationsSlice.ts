import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { AppNotification } from '../../types/api';

export interface NotificationsState {
  items: AppNotification[];
  unread: number;
}

const initialState: NotificationsState = { items: [], unread: 0 };

const notificationsSlice = createSlice({
  name: 'notifications',
  initialState,
  reducers: {
    notificationsLoaded(_state, action: PayloadAction<NotificationsState>) {
      return action.payload;
    },
    notificationsOpened(state) {
      // Optimistic: the saga tells the server.
      state.unread = 0;
      state.items = state.items.map((n) => ({ ...n, read: true }));
    },
    notificationsCleared() {
      return initialState;
    },
  },
});

export const { notificationsLoaded, notificationsOpened, notificationsCleared } = notificationsSlice.actions;
export default notificationsSlice.reducer;
