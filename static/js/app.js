/**
 * Watchlazy - Progressive Enhancement JavaScript
 * Handles watched status, reactions, and personalized recommendations
 */
(function() {
    'use strict';

    const WATCHED_KEY = 'watchlazyWatched';
    const REACTIONS_KEY = 'watchlazyReactions';

    // ========== Toast Notifications ==========
    window.showToast = function(message, type) {
        const toast = document.getElementById('toast');
        if (!toast) return;

        toast.textContent = message;
        toast.className = 'toast show ' + (type || '');

        setTimeout(() => {
            toast.classList.remove('show');
        }, 3000);
    };

    // ========== Watched Status ==========
    window.getWatchedMovies = function() {
        try {
            return JSON.parse(localStorage.getItem(WATCHED_KEY) || '{}');
        } catch (e) {
            return {};
        }
    };

    window.isWatched = function(movieSlug) {
        const watched = window.getWatchedMovies();
        return !!watched[movieSlug];
    };

    window.toggleWatched = function(movieSlug) {
        const watched = window.getWatchedMovies();

        if (watched[movieSlug]) {
            delete watched[movieSlug];
            window.showToast('Removed from watched', 'removed');
        } else {
            watched[movieSlug] = {
                timestamp: Date.now(),
                genres: getMovieGenres(movieSlug)
            };
            window.showToast('Marked as watched', 'success');
        }

        localStorage.setItem(WATCHED_KEY, JSON.stringify(watched));
        updateWatchedUI(movieSlug);
    };

    function updateWatchedUI(movieSlug) {
        const card = document.querySelector('[data-movie-slug="' + movieSlug + '"]');
        if (card) {
            const isWatched = window.isWatched(movieSlug);
            card.classList.toggle('watched', isWatched);
            const btn = card.querySelector('.watched-btn');
            if (btn) btn.classList.toggle('active', isWatched);
        }
    }

    // ========== Star Ratings ==========
    window.getReactions = function() {
        try {
            const data = JSON.parse(localStorage.getItem(REACTIONS_KEY) || '{}');
            // Migrate old reaction format to star ratings
            let needsSave = false;
            Object.keys(data).forEach(function(slug) {
                if (data[slug].reaction && !data[slug].rating) {
                    // Convert old reactions to star ratings
                    const reactionToStars = {
                        'loved': 5,
                        'liked': 4,
                        'disliked': 2
                    };
                    data[slug].rating = reactionToStars[data[slug].reaction] || 3;
                    delete data[slug].reaction;
                    needsSave = true;
                }
            });
            if (needsSave) {
                localStorage.setItem(REACTIONS_KEY, JSON.stringify(data));
            }
            return data;
        } catch (e) {
            return {};
        }
    };

    window.getRating = function(movieSlug) {
        const reactions = window.getReactions();
        return reactions[movieSlug] ? reactions[movieSlug].rating : 0;
    };

    window.setRating = function(movieSlug, stars) {
        const reactions = window.getReactions();

        if (reactions[movieSlug] && reactions[movieSlug].rating === stars) {
            // Clicking same rating removes it
            delete reactions[movieSlug];
            window.showToast('Rating removed', '');
        } else {
            reactions[movieSlug] = {
                rating: stars,
                timestamp: Date.now(),
                genres: getMovieGenres(movieSlug)
            };

            const messages = {
                1: 'Rated 1 star',
                2: 'Rated 2 stars',
                3: 'Rated 3 stars',
                4: 'Rated 4 stars',
                5: 'Rated 5 stars'
            };
            window.showToast(messages[stars] || 'Rating saved', 'success');
        }

        localStorage.setItem(REACTIONS_KEY, JSON.stringify(reactions));
        updateRatingUI(movieSlug);
    };

    function updateRatingUI(movieSlug) {
        const card = document.querySelector('[data-movie-slug="' + movieSlug + '"]');
        if (card) {
            const rating = window.getRating(movieSlug);
            const starContainer = card.querySelector('.star-rating');
            if (starContainer) {
                starContainer.querySelectorAll('.star').forEach(function(star) {
                    const value = parseInt(star.dataset.value);
                    star.classList.toggle('filled', value <= rating);
                    star.textContent = value <= rating ? '\u2605' : '\u2606';
                });
            }
        }
    }

    // ========== Helper to get movie genres from data attribute ==========
    function getMovieGenres(movieSlug) {
        const card = document.querySelector('[data-movie-slug="' + movieSlug + '"]');
        if (card && card.dataset.genres) {
            return card.dataset.genres.split(',');
        }
        return [];
    }

    // ========== Initialize UI States on Page Load ==========
    function initUserStates() {
        const watched = window.getWatchedMovies();
        const reactions = window.getReactions();

        document.querySelectorAll('.movie-card[data-movie-slug], .free-movie-card[data-movie-slug]').forEach(function(card) {
            const slug = card.dataset.movieSlug;

            // Set watched state
            if (watched[slug]) {
                card.classList.add('watched');
                const btn = card.querySelector('.watched-btn');
                if (btn) btn.classList.add('active');
            }

            // Set star rating state
            if (reactions[slug] && reactions[slug].rating) {
                const rating = reactions[slug].rating;
                const starContainer = card.querySelector('.star-rating');
                if (starContainer) {
                    starContainer.querySelectorAll('.star').forEach(function(star) {
                        const value = parseInt(star.dataset.value);
                        star.classList.toggle('filled', value <= rating);
                        star.textContent = value <= rating ? '\u2605' : '\u2606';
                    });
                }
            }
        });
    }

    // ========== For Me Page - Recommendation Engine ==========
    function initForMePage() {
        const forMeContainer = document.getElementById('forMeContent');
        if (!forMeContainer) return;

        // Hide loading indicator first to avoid stuck loading state
        const loadingEl = document.getElementById('forMeLoading');
        
        function hideLoading() {
            if (loadingEl) loadingEl.style.display = 'none';
        }

        try {
            hideLoading();

            const allMoviesData = window.allMoviesData || [];
            if (!Array.isArray(allMoviesData) || allMoviesData.length === 0) {
                forMeContainer.innerHTML = '<div class="no-preferences">' +
                    '<div class="no-preferences-icon">⚠️</div>' +
                    '<h3>Unable to load movies</h3>' +
                    '<p>Please try refreshing the page.</p>' +
                    '<a href="/browse" class="start-exploring-btn">Browse All Movies</a>' +
                    '</div>';
                return;
            }

        const watched = window.getWatchedMovies();
        const reactions = window.getReactions();

        // Calculate user preferences
        const genreScores = {};
        const watchedSlugs = {};
        Object.keys(watched).forEach(function(slug) {
            watchedSlugs[slug] = true;
        });

        // Score genres based on star ratings
        Object.keys(reactions).forEach(function(slug) {
            const data = reactions[slug];
            const genres = data.genres || [];
            // Convert rating to weight: 5 stars = 3, 4 stars = 2, 3 stars = 1, 1-2 stars = -1
            const rating = data.rating || 0;
            const weight = rating >= 5 ? 3 : (rating >= 4 ? 2 : (rating >= 3 ? 1 : -1));

            genres.forEach(function(genre) {
                genreScores[genre] = (genreScores[genre] || 0) + weight;
            });
        });

        // Also weight watched movies positively
        Object.keys(watched).forEach(function(slug) {
            const data = watched[slug];
            const genres = data.genres || [];
            genres.forEach(function(genre) {
                genreScores[genre] = (genreScores[genre] || 0) + 1;
            });
        });

        // Check if user has any preferences
        const hasPreferences = Object.keys(reactions).length > 0 || Object.keys(watched).length > 0;

        if (!hasPreferences) {
            forMeContainer.innerHTML = '<div class="no-preferences">' +
                '<div class="no-preferences-icon">🎬</div>' +
                '<h3>No watch history yet</h3>' +
                '<p>Start watching and rating movies to get personalized recommendations based on your taste!</p>' +
                '<a href="/browse" class="start-exploring-btn">Explore Movies</a>' +
                '</div>';
            return;
        }

        // Show preference summary
        const topGenres = Object.keys(genreScores)
            .filter(function(genre) { return genreScores[genre] > 0; })
            .sort(function(a, b) { return genreScores[b] - genreScores[a]; })
            .slice(0, 5);

        const watchedCount = Object.keys(watched).length;
        const ratedCount = Object.keys(reactions).filter(function(slug) {
            return reactions[slug].rating >= 4;
        }).length;

        var summaryHtml = '<div class="preference-summary">' +
            '<div class="pref-item"><span>Watched</span><span class="count">' + watchedCount + '</span></div>' +
            '<div class="pref-item"><span>Highly Rated</span><span class="count">' + ratedCount + '</span></div>';

        topGenres.slice(0, 3).forEach(function(genre) {
            summaryHtml += '<div class="pref-item"><span>' + genre + '</span></div>';
        });
        summaryHtml += '</div>';

        // Score all movies
        const scoredMovies = allMoviesData
            .filter(function(movie) { return !watchedSlugs[movie.slug]; })
            .map(function(movie) {
                var score = 0;
                (movie.genres || []).forEach(function(genre) {
                    score += (genreScores[genre] || 0) * 10;
                });
                if (movie.rating) {
                    score += movie.rating * 2;
                }
                movie.recScore = score;
                return movie;
            })
            .filter(function(movie) { return movie.recScore > 0; })
            .sort(function(a, b) { return b.recScore - a.recScore; });

        if (scoredMovies.length === 0) {
            forMeContainer.innerHTML = summaryHtml +
                '<div class="no-preferences" style="padding-top: 40px;">' +
                '<h3>You\'ve seen everything we\'d recommend!</h3>' +
                '<p>Check out the browse page for more movies.</p>' +
                '<a href="/browse" class="start-exploring-btn">Browse All Movies</a>' +
                '</div>';
            return;
        }

        // Build HTML
        var html = summaryHtml;

        // Top picks section
        html += '<section class="rec-section">' +
            '<div class="rec-section-header">' +
            '<h2>Top Picks For You</h2>' +
            '<span class="reason">Based on your preferences</span>' +
            '</div>' +
            '<div class="movies-grid">';

        scoredMovies.slice(0, 12).forEach(function(movie) {
            html += createMovieCardHtml(movie);
        });

        html += '</div></section>';

        // Genre-specific sections
        topGenres.slice(0, 3).forEach(function(genre) {
            const genreMovies = scoredMovies
                .filter(function(m) { return (m.genres || []).indexOf(genre) !== -1; })
                .slice(0, 6);

            if (genreMovies.length > 0) {
                html += '<section class="rec-section">' +
                    '<div class="rec-section-header">' +
                    '<h2>Because you like ' + genre + '</h2>' +
                    '</div>' +
                    '<div class="movies-grid">';

                genreMovies.forEach(function(movie) {
                    html += createMovieCardHtml(movie);
                });

                html += '</div></section>';
            }
        });

        forMeContainer.innerHTML = html;

        // Re-init states for new cards
        initUserStates();
        } catch (error) {
            console.error('Error initializing For Me page:', error);
            hideLoading();
            forMeContainer.innerHTML = '<div class="no-preferences">' +
                '<div class="no-preferences-icon">⚠️</div>' +
                '<h3>Something went wrong</h3>' +
                '<p>Please try refreshing the page.</p>' +
                '<a href="/browse" class="start-exploring-btn">Browse All Movies</a>' +
                '</div>';
        }
    }

    function createMovieCardHtml(movie) {
        const genres = (movie.genres || []).join(',');
        const synopsis = movie.synopsis ?
            (movie.synopsis.length > 150 ? movie.synopsis.substring(0, 150) + '...' : movie.synopsis) : '';

        var html = '<article class="movie-card" data-movie-slug="' + movie.slug + '" data-genres="' + genres + '">' +
            '<a href="/movie/' + movie.slug + '">' +
            '<div class="poster-container">';

        if (movie.poster_url) {
            html += '<img src="' + movie.poster_url + '" alt="' + movie.title + ' poster" loading="lazy" class="movie-poster">';
        } else {
            html += '<div class="movie-poster" style="display: flex; align-items: center; justify-content: center; font-size: 3rem; color: var(--text-muted);">🎬</div>';
        }

        html += '<span class="watched-badge" style="display: none;">Watched</span>' +
            '</div>' +
            '<div class="movie-info">' +
            '<h3 class="movie-title">' + movie.title + '</h3>' +
            '<div class="movie-meta">';

        if (movie.year) {
            html += '<span>' + movie.year + '</span>';
        }
        if (movie.rating) {
            html += '<span class="movie-rating">' + movie.rating + ' IMDb</span>';
        }

        html += '</div>';

        if (synopsis) {
            html += '<p class="movie-synopsis">' + synopsis + '</p>';
        }

        html += '<div class="movie-services">';
        if (movie.is_free) {
            html += '<span class="service-tag service-tag-free">Free</span>';
        } else if (movie.has_subscription) {
            html += '<span class="service-tag service-tag-sub">Subscription</span>';
        }
        html += '</div></div></a>' +
            '<button class="watched-btn" onclick="event.preventDefault(); event.stopPropagation(); toggleWatched(\'' + movie.slug + '\')" title="Mark as watched">' +
            '<span class="watched-text">Watched</span>' +
            '</button>' +
            '<div class="star-rating">' +
            '<span class="star" data-value="1" onclick="event.preventDefault(); event.stopPropagation(); setRating(\'' + movie.slug + '\', 1)" title="1 star">☆</span>' +
            '<span class="star" data-value="2" onclick="event.preventDefault(); event.stopPropagation(); setRating(\'' + movie.slug + '\', 2)" title="2 stars">☆</span>' +
            '<span class="star" data-value="3" onclick="event.preventDefault(); event.stopPropagation(); setRating(\'' + movie.slug + '\', 3)" title="3 stars">☆</span>' +
            '<span class="star" data-value="4" onclick="event.preventDefault(); event.stopPropagation(); setRating(\'' + movie.slug + '\', 4)" title="4 stars">☆</span>' +
            '<span class="star" data-value="5" onclick="event.preventDefault(); event.stopPropagation(); setRating(\'' + movie.slug + '\', 5)" title="5 stars">☆</span>' +
            '</div></article>';

        return html;
    }

    // ========== Mobile Search ==========
    function initMobileSearch() {
        const searchBox = document.querySelector('.search-box');
        const searchInput = searchBox ? searchBox.querySelector('input') : null;
        const searchBtn = searchBox ? searchBox.querySelector('button') : null;

        if (!searchBox || !searchInput || !searchBtn) return;

        // Expand when input is focused
        searchInput.addEventListener('focus', function() {
            if (window.innerWidth <= 480) {
                searchBox.classList.add('expanded');
            }
        });

        searchBtn.addEventListener('click', function(e) {
            // Check if we're in mobile view (480px or less)
            if (window.innerWidth <= 480) {
                const isExpanded = searchBox.classList.contains('expanded');

                // First click: always expand and focus
                if (!isExpanded) {
                    e.preventDefault();
                    e.stopPropagation();
                    searchBox.classList.add('expanded');
                    searchInput.focus();
                    searchInput.select(); // Select text so user can type new query
                    return;
                }

                // Already expanded: submit if has text, otherwise just focus
                if (!searchInput.value.trim()) {
                    e.preventDefault();
                    e.stopPropagation();
                    searchInput.focus();
                }
                // If has text, let the form submit normally
            }
        });

        // Collapse when clicking outside search box
        document.addEventListener('click', function(e) {
            if (window.innerWidth <= 480 && searchBox.classList.contains('expanded')) {
                if (!searchBox.contains(e.target)) {
                    searchBox.classList.remove('expanded');
                }
            }
        });
    }

    // ========== Mobile Navigation ==========
    function initMobileNav() {
        const hamburger = document.getElementById('hamburger');
        const mobileNav = document.getElementById('mobileNav');
        const closeNav = document.getElementById('closeNav');

        if (!hamburger || !mobileNav) return;

        hamburger.addEventListener('click', function() {
            hamburger.classList.toggle('active');
            mobileNav.classList.toggle('active');
            document.body.style.overflow = mobileNav.classList.contains('active') ? 'hidden' : '';
        });

        if (closeNav) {
            closeNav.addEventListener('click', function() {
                hamburger.classList.remove('active');
                mobileNav.classList.remove('active');
                document.body.style.overflow = '';
            });
        }

        // Toggle dropdowns in mobile nav
        mobileNav.querySelectorAll('.nav-dropdown > .nav-link').forEach(function(link) {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                this.parentElement.classList.toggle('open');
            });
        });
    }

    // ========== Google Analytics Event Tracking ==========
    function initMovieClickTracking() {
        document.addEventListener('click', function(e) {
            // Find if click was on a movie card link
            const movieCard = e.target.closest('.movie-card, .free-movie-card');
            if (!movieCard) return;

            const link = e.target.closest('a');
            if (!link) return;

            const slug = movieCard.dataset.movieSlug;
            const titleEl = movieCard.querySelector('.movie-title');
            const title = titleEl ? titleEl.textContent : slug;

            // Send event to Google Analytics
            if (typeof gtag === 'function') {
                gtag('event', 'movie_click', {
                    movie_slug: slug,
                    movie_title: title
                });
            }
        });
    }

    // ========== Initialize on DOM Ready ==========
    function init() {
        initUserStates();
        initForMePage();
        initMobileNav();
        initMobileSearch();
        initMovieClickTracking();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
