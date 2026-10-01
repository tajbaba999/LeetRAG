# GraphQL documents for leetcode.com/graphql, copied verbatim from the Express backend.

GET_CALENDAR = """
  query userProfileCalendar($username: String!, $year: Int) {
    matchedUser(username: $username) {
      userCalendar(year: $year) {
        activeYears
        streak
        totalActiveDays
        dccBadges {
          timestamp
          badge {
            name
            icon
          }
        }
        submissionCalendar
      }
    }
  }
"""

GET_CONTEST_RANKING = """
  query userContestRankingInfo($username: String!) {
    userContestRanking(username: $username) {
      attendedContestsCount
      rating
      globalRanking
      totalParticipants
      topPercentage
      badge {
        name
      }
    }
    userContestRankingHistory(username: $username) {
      attended
      trendDirection
      problemsSolved
      totalProblems
      finishTimeInSeconds
      rating
      ranking
      contest {
        title
        startTime
      }
    }
  }
"""

GET_LANGUAGE_STATS = """
  query languageStats($username: String!) {
    matchedUser(username: $username) {
      languageProblemCount {
        languageName
        problemsSolved
      }
    }
  }
"""

GET_USER_PROFILE = """
  query getUserProfile($username: String!) {
    allQuestionsCount {
      difficulty
      count
    }
    matchedUser(username: $username) {
      contributions {
        points
      }
      profile {
        reputation
        ranking
      }
      submissionCalendar
      submitStats {
        acSubmissionNum {
          difficulty
          count
          submissions
        }
        totalSubmissionNum {
          difficulty
          count
          submissions
        }
      }
    }
    recentSubmissionList(username: $username, limit: 20) {
      title
      titleSlug
      timestamp
      statusDisplay
      lang
    }
    matchedUserStats: matchedUser(username: $username) {
      submitStats: submitStatsGlobal {
        acSubmissionNum {
          difficulty
          count
          submissions
        }
        totalSubmissionNum {
          difficulty
          count
          submissions
        }
      }
    }
  }
"""

GET_QUESTION_PROGRESS = """
  query userProfileUserQuestionProgressV2($username: String!) {
    userProfileUserQuestionProgressV2(userSlug: $username) {
      numAcceptedQuestions {
        count
        difficulty
      }
      numFailedQuestions {
        count
        difficulty
      }
      numUntouchedQuestions {
        count
        difficulty
      }
      userSessionBeatsPercentage {
        difficulty
        percentage
      }
      totalQuestionBeatsPercentage
    }
  }
"""

GET_SESSION_PROGRESS = """
  query userSessionProgress($username: String!) {
    allQuestionsCount {
      difficulty
      count
    }
    matchedUser(username: $username) {
      submitStats {
        acSubmissionNum {
          difficulty
          count
          submissions
        }
        totalSubmissionNum {
          difficulty
          count
          submissions
        }
      }
    }
  }
"""

GET_SKILL_STATS = """
  query skillStats($username: String!) {
    matchedUser(username: $username) {
      tagProblemCounts {
        advanced {
          tagName
          tagSlug
          problemsSolved
        }
        intermediate {
          tagName
          tagSlug
          problemsSolved
        }
        fundamental {
          tagName
          tagSlug
          problemsSolved
        }
      }
    }
  }
"""

GET_USER_PROGRESS_QUESTIONS = """
  query userProgressQuestionList($filters: UserProgressQuestionListInput) {
    userProgressQuestionList(filters: $filters) {
      totalNum
      questions {
        translatedTitle
        frontendId
        title
        titleSlug
        difficulty
        lastSubmittedAt
        numSubmitted
        questionStatus
        lastResult
        topicTags {
          name
          nameTranslated
          slug
        }
      }
    }
  }
"""

# From the leetcode-query npm package (`LeetCode.user()`), used by GET /leetcode/{username}.
GET_PUBLIC_PROFILE = """query ($username: String!) {
    allQuestionsCount {
        difficulty
        count
    }
    matchedUser(username: $username) {
        username
        socialAccounts
        githubUrl
        contributions {
            points
            questionCount
            testcaseCount
        }
        profile {
            realName
            websites
            countryName
            skillTags
            company
            school
            starRating
            aboutMe
            userAvatar
            reputation
            ranking
        }
        submissionCalendar
        submitStats {
            acSubmissionNum {
                difficulty
                count
                submissions
            }
            totalSubmissionNum {
                difficulty
                count
                submissions
            }
        }
        badges {
            id
            displayName
            icon
            creationDate
        }
        upcomingBadges {
            name
            icon
        }
        activeBadge {
            id
        }
    }
    recentSubmissionList(username: $username, limit: 20) {
        title
        titleSlug
        timestamp
        statusDisplay
        lang
    }
}
"""
