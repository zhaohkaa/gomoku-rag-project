"""
Game Logic Module for Gomoku
Handles board state, move validation, and win detection
"""

from typing import Optional, Tuple, List
from dataclasses import dataclass, field


# Constants
EMPTY = 0
BLACK = 1  # Human player
WHITE = 2  # AI player
BOARD_SIZE = 15
WIN_COUNT = 5


@dataclass
class GomokuGame:
    """Gomoku game state manager"""

    board: List[List[int]] = field(default_factory=lambda: [[EMPTY] * BOARD_SIZE for _ in range(BOARD_SIZE)])
    current_player: int = BLACK
    move_history: List[Tuple[int, int, int]] = field(default_factory=list)  # (x, y, player)
    game_over: bool = False
    winner: Optional[int] = None

    def reset(self):
        """Reset the game to initial state"""
        self.board = [[EMPTY] * BOARD_SIZE for _ in range(BOARD_SIZE)]
        self.current_player = BLACK
        self.move_history = []
        self.game_over = False
        self.winner = None

    def is_valid_move(self, x: int, y: int) -> bool:
        """Check if a move is valid"""
        if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
            return False
        if self.board[y][x] != EMPTY:
            return False
        if self.game_over:
            return False
        return True

    def make_move(self, x: int, y: int) -> bool:
        """Make a move on the board"""
        if not self.is_valid_move(x, y):
            return False

        self.board[y][x] = self.current_player
        self.move_history.append((x, y, self.current_player))

        # Check for win
        if self._check_win(x, y):
            self.game_over = True
            self.winner = self.current_player

        # Check for draw
        elif self._is_board_full():
            self.game_over = True
            self.winner = None

        # Switch player
        self.current_player = WHITE if self.current_player == BLACK else BLACK

        return True

    def _check_win(self, x: int, y: int) -> bool:
        """Check if the last move at (x, y) resulted in a win"""
        player = self.board[y][x]
        directions = [
            (1, 0),   # Horizontal
            (0, 1),   # Vertical
            (1, 1),   # Main diagonal
            (1, -1),  # Anti-diagonal
        ]

        for dx, dy in directions:
            count = 1
            count += self._count_direction(x, y, dx, dy, player)
            count += self._count_direction(x, y, -dx, -dy, player)

            if count >= WIN_COUNT:
                return True

        return False

    def _count_direction(self, x: int, y: int, dx: int, dy: int, player: int) -> int:
        """Count consecutive pieces in a direction"""
        count = 0
        nx, ny = x + dx, y + dy

        while 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE:
            if self.board[ny][nx] == player:
                count += 1
                nx += dx
                ny += dy
            else:
                break

        return count

    def _is_board_full(self) -> bool:
        """Check if the board is full"""
        for row in self.board:
            if EMPTY in row:
                return False
        return True

    def get_winning_line(self) -> Optional[List[Tuple[int, int]]]:
        """Get the coordinates of the winning line if game is over"""
        if not self.game_over or self.winner is None:
            return None

        # Find the last move that caused the win
        last_x, last_y, last_player = self.move_history[-1]
        if last_player != self.winner:
            return None

        player = self.winner
        directions = [
            (1, 0),   # Horizontal
            (0, 1),   # Vertical
            (1, 1),   # Main diagonal
            (1, -1),  # Anti-diagonal
        ]

        for dx, dy in directions:
            line = [(last_x, last_y)]
            line.extend(self._get_line_direction(last_x, last_y, dx, dy, player))
            line.extend(self._get_line_direction(last_x, last_y, -dx, -dy, player))

            if len(line) >= WIN_COUNT:
                return line[:WIN_COUNT]

        return None

    def _get_line_direction(self, x: int, y: int, dx: int, dy: int, player: int) -> List[Tuple[int, int]]:
        """Get all consecutive pieces in a direction"""
        result = []
        nx, ny = x + dx, y + dy

        while 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE:
            if self.board[ny][nx] == player:
                result.append((nx, ny))
                nx += dx
                ny += dy
            else:
                break

        return result

    def board_to_string(self) -> str:
        """Convert board to string representation for AI prompt"""
        lines = []
        for row in self.board:
            lines.append(str(row))
        return "\n".join(lines)
