def get_matched_users(user_prefrences, proxy_prefrences, capacities):
    """
    The deferred acceptance algorithm from the Enem19 paper
    """
    waiting_users = [student for student in user_prefrences]
    assignment_results = {choice: [] for choice in capacities}

    def get_waiting_list_without_student(student):
        return [x for x in waiting_users if x != student]

    def get_sorted_results_with_student(student, choice):
        assignment_results[choice].append(student)
        return [x for x in proxy_prefrences[choice] if x in assignment_results[choice]]

    while waiting_users:
        for student in waiting_users.copy():
            if not user_prefrences[student]:
                waiting_users = get_waiting_list_without_student(student)
                continue
            choice = user_prefrences[student].pop(0)
            if len(assignment_results[choice]) < capacities[choice]:
                assignment_results[choice] = get_sorted_results_with_student(
                    student, choice
                )
                waiting_users = get_waiting_list_without_student(student)
            else:
                if proxy_prefrences[choice].index(student) < proxy_prefrences[
                    choice
                ].index(assignment_results[choice][-1]):
                    assignment_results[choice] = get_sorted_results_with_student(
                        student, choice
                    )
                    waiting_users = get_waiting_list_without_student(student)
                    waiting_users.append(assignment_results[choice].pop())

    return assignment_results


if __name__ == "__main__":
    # run test
    user_preferences = {
        "user1": ["proxy1", "proxy2", "proxy3"],
        "user2": ["proxy1", "proxy2", "proxy3"],
        "user3": ["proxy2", "proxy3", "proxy1"],
    }

    proxy_preferences = {
        "proxy1": ["user2", "user3", "user1"],
        "proxy2": ["user1", "user3", "user2"],
        "proxy3": ["user2", "user1", "user3"],
    }

    proxy_capacities = {"proxy1": 1, "proxy2": 2, "proxy3": 1}

    print(get_matched_users(user_preferences, proxy_preferences, proxy_capacities))
