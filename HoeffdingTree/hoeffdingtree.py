import math
from operator import attrgetter

from core import utils
from core.attribute import Attribute
from core.instance import Instance
from core.dataset import Dataset

from ht.activehnode import ActiveHNode
from ht.ginisplitmetric import GiniSplitMetric
from ht.hnode import HNode
from ht.inactivehnode import InactiveHNode
from ht.infogainsplitmetric import InfoGainSplitMetric
from ht.leafnode import LeafNode
from ht.splitcandidate import SplitCandidate
from ht.splitmetric import SplitMetric
from ht.splitnode import SplitNode

class HoeffdingTree(object):
    """Main class for a Hoeffding Tree, also known as Very Fast Decision Tree (VFDT)."""

    def __init__(self):
        self._header = None
        self._root = None
        self._grace_period = 200
        self._split_confidence = 0.0000001
        self._hoeffding_tie_threshold = 0.05
        self._min_frac_weight_for_two_branches_gain = 0.01

        # Split metric stuff goes here
        self.GINI_SPLIT = 0
        self.INFO_GAIN_SPLIT = 1

        self._selected_split_metric = self.INFO_GAIN_SPLIT
        self._split_metric = InfoGainSplitMetric(self._min_frac_weight_for_two_branches_gain)
        # self._selected_split_metric = self.GINI_SPLIT
        # self._split_metric = GiniSplitMetric()

        # Leaf prediction strategy stuff goes here

        # Only used when the leaf prediction strategy is baded on Naive Bayes, not useful right now
        # self._nb_threshold = 0

        self._active_leaf_count = 0
        self._inactive_leaf_count = 0
        self._decision_node_count = 0

        # Print out leaf models in the case of naive Bayes or naive Bayes adaptive leaves 
        self._print_leaf_models = False

    def __str__(self):
        if self._root is None:
            return '目前还是空Hoeffding树!'
        return self._root.__str__(self._print_leaf_models)

    # 重置分类器并将所有 节点/叶节点 的计数器设置为零
    # Reset the classifier and set all node/leaf counters to zero.
    def reset(self):
        self._root = None
        self._active_leaf_count = 0
        self._inactive_leaf_count = 0
        self._decision_node_count = 0

    def set_minimum_fraction_of_weight_info_gain(self, m):
        self._min_frac_weight_for_two_branches_gain = m

    def get_minimum_fraction_of_weight_info_gain(self):
        return self._min_frac_weight_for_two_branches_gain

    def set_grace_period(self, grace):
        self._grace_period = grace

    def get_grace_period(self):
        return self._grace_period

    def set_hoeffding_tie_threshold(self, ht):
        self._hoeffding_tie_threshold = ht

    def get_hoeffding_tie_threshold(self):
        return self._hoeffding_tie_threshold

    def set_split_confidence(self, sc):
        self._split_confidence = sc

    def get_split_confidence(self):
        return self._split_confidence

    def compute_hoeffding_bound(self, max_value, confidence, weight):
        """Calculate the Hoeffding bound.

        Args:
            max_value (float): 
            confidence (float):
            weight (float): 

        Returns:
            (float): The Hoeffding bound.
        """
        return math.sqrt(((max_value * max_value) * math.log(1.0 / confidence)) / (2.0 * weight))

    def build_classifier(self, dataset):
        """Build the classifier.

        Args:
            dataset (Dataset): The data to start training the classifier.
        """
        self.reset()
        self._header = dataset
        if self._selected_split_metric is self.GINI_SPLIT:
            self._split_metric = GiniSplitMetric()
        else:
            self._split_metric = InfoGainSplitMetric(self._min_frac_weight_for_two_branches_gain)
        # for循环遍历数据集，模拟流数据，一条条获取实例
        for i in range(dataset.num_instances()):
            self.update_classifier(dataset.instance(i))

    def update_classifier(self, instance):
        """用参数中传来的实例更新分类器。

        Args:
            instance (Instance): The new instance to be used to train the classifier.
        """
        if instance.class_is_missing():
            return
        if self._root is None:
            self._root = self.new_learning_node()

        l = self._root.leaf_for_instance(instance, None, None)
        actual_node = l.the_node
        if actual_node is None:
            actual_node = ActiveHNode()
            l.parent_node.set_child(l.parent_branch, actual_node)

        # ActiveHNode should be changed to a LearningNode interface if Naive Bayes nodes are used
        if isinstance(actual_node, InactiveHNode):
            actual_node.update_node(instance)
        if isinstance(actual_node, ActiveHNode):
            actual_node.update_node(instance)
            total_weight = actual_node.total_weight()
            if total_weight - actual_node.weight_seen_at_last_split_eval > self._grace_period:
                self.try_split(actual_node, l.parent_node, l.parent_branch)
                actual_node.weight_seen_at_last_split_eval = total_weight

    def distribution_for_instance(self, instance):
        """
        返回实例的类概率。
        Return the class probabilities for an instance.

        Args:
            instance (Instance): The instance to calculate the class probabilites for.

        Returns:
            list[float]: The class probabilities.
        """
        # 获取实例的类属性
        class_attribute = instance.class_attribute()
        # 用来存放返回值，即实例的类概率
        pred = []

        if self._root is not None:
            l = self._root.leaf_for_instance(instance, None, None)
            actual_node = l.the_node
            if actual_node is None:
                actual_node = l.parent_node
            pred = actual_node.get_distribution(instance, class_attribute)
        else:
            # All class values equally likely
            pred = [1 for i in range(class_attribute.num_values())]
            pred = utils.normalize(pred)

        return pred

    def deactivate_node(self, to_deactivate, parent, parent_branch):
        """
        阻止节点增长。
        Prevent supplied node of growing.

        Args:
            to_deactivate (ActiveHNode): The node to be deactivated.要停止增长的节点
            parent (SplitNode): The parent of the node.父节点
            parent_branch (str): The branch leading from the parent to the node.从父节点到节点的分支。
        """
        leaf = InactiveHNode(to_deactivate.class_distribution)

        if parent is None:
            self._root = leaf
        else:
            parent.set_child(parent_branch, leaf)

        self._active_leaf_count -= 1
        self._inactive_leaf_count += 1

    def activate_node(self, to_activate, parent, parent_branch):
        """
        允许节点增长。
        Allow supplied node to grow.

        Args:
            to_activate (InactiveHNode): The node to be activated.
            parent (SplitNode): The parent of the node.
            parent_branch (str): The branch leading from the parent to the node.
        """
        leaf = ActiveHNode()
        leaf.class_distribution = to_activate.class_distribution

        if parent is None:
            self._root = leaf
        else:
            parent.set_child(parent_branch, leaf)

        self._active_leaf_count += 1
        self._inactive_leaf_count -= 1

    def try_split(self, node, parent, parent_branch):
        """Try a split from the supplied node.

        Args:
            node (ActiveHNode): The node to split.
            parent (SplitNode): The parent of the node.
            parent_branch (str): The branch leading from the parent to the node.
        """
        # Non-pure?
        if node.num_entries_in_class_distribution() > 1:
            best_splits = node.get_possible_splits(self._split_metric)
            best_splits.sort(key=attrgetter('split_merit'))

            do_split = False
            if len(best_splits) < 2:
                do_split = len(best_splits) > 0
            else:
                # Compute Hoeffding bound
                metric_max = self._split_metric.get_metric_range(node.class_distribution)
                hoeffding_bound = self.compute_hoeffding_bound(
                    metric_max, self._split_confidence, node.total_weight())
                best = best_splits[len(best_splits) - 1]
                second_best = best_splits[len(best_splits) - 2]
                if best.split_merit - second_best.split_merit > hoeffding_bound or hoeffding_bound < self._hoeffding_tie_threshold:
                    do_split = True

            if do_split:
                best = best_splits[len(best_splits) - 1]
                if best.split_test is None:
                    # preprune
                    self.deactivate_node(node, parent, parent_branch)
                else:
                    new_split = SplitNode(node.class_distribution, best.split_test)

                    for i in range(best.num_splits()):
                        new_child = self.new_learning_node()
                        new_child.class_distribution = best.post_split_class_distributions[i]
                        new_child.weight_seen_at_last_split_eval = new_child.total_weight()
                        branch_name = ''
                        if self._header.attribute(name=best.split_test.split_attributes()[0]).is_numeric():
                            if i is 0:
                                branch_name = 'left'
                            else:
                                branch_name = 'right'
                        else:
                            split_attribute = self._header.attribute(name=best.split_test.split_attributes()[0])
                            branch_name = split_attribute.value(i)
                        new_split.set_child(branch_name, new_child)

                    self._active_leaf_count -= 1
                    self._decision_node_count += 1
                    self._active_leaf_count += best.num_splits()

                    if parent is None:
                        self._root = new_split
                    else:
                        parent.set_child(parent_branch, new_split)

    def new_learning_node(self):
        """
        创建新的学习节点。将始终是ActiveHNode，而naivebayes节点未实现。
        Create a new learning node. Will always be an ActiveHNode while Naive Bayes
        nodes are not implemented.

        Returns:
            ActiveHNode: The new learning node.
        """
        # Leaf strategy should be handled here if/when the Naive Bayes approach is implemented
        return ActiveHNode()
