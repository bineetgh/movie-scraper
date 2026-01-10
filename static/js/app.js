/**
 * Watchlazy - Progressive Enhancement JavaScript
 * Works without JS, enhanced with JS for interactive features
 */
(function() {
    'use strict';

    const STORAGE_KEY = 'myMovieList';
    const REACTIONS_KEY = 'movieReactions';
    const WATCHED_KEY = 'watchedMovies';

    // Initialize on DOM ready
    document.addEventListener('DOMContentLoaded', function() {
        initSearch();
        initToast();
    });

    // Search with instant suggestions
    function initSearch() {
        const searchInput = document.querySelector('.search-box input');
        if (!searchInput) return;

        let debounceTimer;
        searchInput.addEventListener('input', function() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                const query = searchInput.value.trim();
                if (query.length >= 2) {
                    // Could add instant search dropdown here
                }
            }, 300);
        });
    }

    // Toast notifications
    function initToast() {
        window.showToast = function(message, type) {
            const toast = document.getElementById('toast');
            if (!toast) return;

            toast.textContent = message;
            toast.className = 'toast show ' + (type || '');

            setTimeout(() => {
                toast.classList.remove('show');
            }, 3000);
        };
    }

    // My List functionality (client-side storage)
    window.getMyList = function() {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        } catch {
            return [];
        }
    };

    window.toggleMyList = function(movieSlug, movieTitle) {
        const list = window.getMyList();
        const index = list.findIndex(item => item.slug === movieSlug);

        if (index > -1) {
            list.splice(index, 1);
            window.showToast('Removed from My List', 'removed');
        } else {
            list.push({ slug: movieSlug, title: movieTitle, addedAt: Date.now() });
            window.showToast('Added to My List', 'success');
        }

        localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
        updateListButtons(movieSlug);
    };

    window.isInMyList = function(movieSlug) {
        const list = window.getMyList();
        return list.some(item => item.slug === movieSlug);
    };

    function updateListButtons(movieSlug) {
        document.querySelectorAll(`[data-movie-slug="${movieSlug}"]`).forEach(btn => {
            btn.classList.toggle('in-list', window.isInMyList(movieSlug));
        });
    }

    // Reactions handling
    window.getReactions = function() {
        try {
            return JSON.parse(localStorage.getItem(REACTIONS_KEY) || '{}');
        } catch {
            return {};
        }
    };

    window.setReaction = function(movieSlug, reaction) {
        const reactions = window.getReactions();

        if (reactions[movieSlug] === reaction) {
            delete reactions[movieSlug];
            window.showToast('Reaction removed', '');
        } else {
            reactions[movieSlug] = reaction;
            window.showToast('Reaction saved', 'success');
        }

        localStorage.setItem(REACTIONS_KEY, JSON.stringify(reactions));
    };

    // Watched status
    window.getWatchedMovies = function() {
        try {
            return JSON.parse(localStorage.getItem(WATCHED_KEY) || '{}');
        } catch {
            return {};
        }
    };

    window.toggleWatched = function(movieSlug) {
        const watched = window.getWatchedMovies();

        if (watched[movieSlug]) {
            delete watched[movieSlug];
            window.showToast('Marked as unwatched', '');
        } else {
            watched[movieSlug] = Date.now();
            window.showToast('Marked as watched', 'success');
        }

        localStorage.setItem(WATCHED_KEY, JSON.stringify(watched));
    };

    window.isWatched = function(movieSlug) {
        const watched = window.getWatchedMovies();
        return !!watched[movieSlug];
    };

})();
