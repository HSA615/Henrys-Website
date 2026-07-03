// 🔥 YOUR Firebase config (PUT YOUR REAL ONE HERE)
const firebaseConfig = {
  apiKey: "YOUR_FIREBASE_API_KEY",
  authDomain: "music-comment-section.firebaseapp.com",
  databaseURL: "https://music-comment-section-default-rtdb.firebaseio.com/", // IMPORTANT for Realtime DB
  projectId: "music-comment-section"
};

// Initialize Firebase
let db;
let commentsRef;

try {
  firebase.initializeApp(firebaseConfig);
  db = firebase.database();
  commentsRef = db.ref("comments");
  console.log("Realtime DB initialized");
} catch (error) {
  console.error("Firebase init error:", error);
}

// Password for deleting comments
const DELETE_PASSWORD = 'henry123';

// DOM Elements
const commentForm = document.getElementById('comment-form');
const commentsList = document.getElementById('comments-list');
const nameInput = document.getElementById('comment-name');
const commentInput = document.getElementById('comment-text');

// Init
document.addEventListener('DOMContentLoaded', () => {
  if (commentsList && commentForm) {
    loadComments();
    commentForm.addEventListener('submit', handleCommentSubmit);
  }
});

// 🔥 LOAD COMMENTS (REALTIME)
function loadComments() {
  if (!commentsRef) {
    console.error("DB not initialized");
    showNoComments();
    return;
  }

  commentsList.innerHTML = '<div class="loading-spinner">Loading comments...</div>';

  commentsRef.on("value", (snapshot) => {
    const data = snapshot.val();

    if (!data) {
      showNoComments();
      return;
    }

    renderComments(data);
  }, (error) => {
    console.error("Error loading comments:", error);
    showNoComments();
  });
}

// 🔥 RENDER COMMENTS
function renderComments(data) {
  commentsList.innerHTML = "";

  const commentsArray = Object.entries(data)
    .map(([id, comment]) => ({ id, ...comment }))
    .sort((a, b) => b.time - a.time);

  commentsArray.forEach(comment => {
    const commentElement = createCommentElement(comment.id, comment);
    commentsList.appendChild(commentElement);
  });
}

// Show "no comments"
function showNoComments() {
  commentsList.innerHTML = '<div class="no-comments">No comments yet. Be the first!</div>';
}

// 🔥 CREATE COMMENT ELEMENT
function createCommentElement(id, comment) {
  const div = document.createElement('div');
  div.className = 'comment-item';

  const date = comment.time 
    ? new Date(comment.time).toLocaleString() 
    : 'Just now';

  div.innerHTML = `
    <div class="comment-header">
      <span class="comment-author">${escapeHtml(comment.name)}</span>
      <span class="comment-date">${date}</span>
    </div>
    <p class="comment-text">${escapeHtml(comment.text)}</p>
    <button class="delete-btn" onclick="showDeleteModal('${id}')">
      🗑
    </button>
  `;

  return div;
}

// 🔥 SUBMIT COMMENT
function handleCommentSubmit(e) {
  e.preventDefault();

  const name = nameInput.value.trim();
  const text = commentInput.value.trim();

  if (!name || !text) {
    showNotification('Fill everything bro', 'error');
    return;
  }

  if (!commentsRef) {
    showNotification('DB error', 'error');
    return;
  }

  commentsRef.push({
    name: name,
    text: text,
    time: Date.now()
  });

  nameInput.value = '';
  commentInput.value = '';

  showNotification('Posted 🔥', 'success');
}

// 🔥 DELETE FLOW
let commentToDelete = null;

function showDeleteModal(id) {
  commentToDelete = id;

  const modal = document.createElement('div');
  modal.className = 'password-modal';
  modal.id = 'delete-modal';

  modal.innerHTML = `
    <div class="modal-overlay" onclick="closeDeleteModal()"></div>
    <div class="modal-content">
      <h3>Delete Comment</h3>
      <input type="password" id="delete-password" placeholder="Password">
      <div class="modal-buttons">
        <button onclick="closeDeleteModal()">Cancel</button>
        <button onclick="confirmDelete()">Delete</button>
      </div>
    </div>
  `;

  document.body.appendChild(modal);
}

// Close modal
function closeDeleteModal() {
  const modal = document.getElementById('delete-modal');
  if (modal) modal.remove();
  commentToDelete = null;
}

// Confirm delete
function confirmDelete() {
  const input = document.getElementById('delete-password');
  const password = input ? input.value : '';

  if (password !== DELETE_PASSWORD) {
    showNotification('Wrong password 💀', 'error');
    return;
  }

  if (!commentToDelete) return;

  commentsRef.child(commentToDelete).remove()
    .then(() => {
      showNotification('Deleted', 'success');
      closeDeleteModal();
    })
    .catch(err => {
      console.error(err);
      showNotification('Delete failed', 'error');
    });
}

// 🔒 Prevent XSS
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// 🔔 Toast
function showNotification(message, type) {
  const existing = document.querySelector('.notification-toast');
  if (existing) existing.remove();

  const notification = document.createElement('div');
  notification.className = `notification-toast ${type}`;
  notification.textContent = message;

  document.body.appendChild(notification);

  requestAnimationFrame(() => {
    notification.classList.add('show');
  });

  setTimeout(() => {
    notification.classList.remove('show');
    setTimeout(() => notification.remove(), 300);
  }, 3000);
}